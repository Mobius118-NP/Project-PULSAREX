import sys
import time
from pathlib import Path
from queue import Queue
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pulsar.config import Config
from pulsar.server import create_app
from pulsar.vision import FrameCache, camera_worker, face_bearing


def test_78_degree_projection_and_orientation():
    assert face_bearing(0) == pytest.approx(321)
    assert face_bearing(.5) == 0
    assert face_bearing(1) == pytest.approx(39)
    assert face_bearing(.5, 90) == 90
    assert face_bearing(1, 350) == pytest.approx(29)
    assert 0 < face_bearing(.75) < 39
    with pytest.raises(ValueError):
        face_bearing(2)


def test_video_cache_bound_and_stale_identity_withholding():
    cache = FrameCache(capacity=8)
    for index in range(1000):
        cache.add({'sequence': index, 'captured_at': 100, 'faces': [{'identity_id': 'TEST-ONLY'}], 'jpeg_base64': 'synthetic'})
    assert len(cache.frames) == 8 and cache.latest(now=100.5)['sequence'] == 999
    assert cache.latest(now=100.5)['faces']
    stale = cache.latest(now=102)
    assert stale['stale'] and not stale['faces']
    cache.clear()
    assert cache.latest() is None


def test_vision_endpoints_protected_and_no_template_payload(tmp_path):
    token = '024681'
    app = create_app(Config(host='0.0.0.0', data_dir=str(tmp_path)), token=token, autostart=False)
    with TestClient(app, base_url='http://127.0.0.1') as client:
        for route in ('vision', 'vision/frame', 'vision/catalogue'):
            assert client.get('/api/v1/'+route).status_code == 401
        assert client.post('/api/v1/vision/start', json={}).status_code == 401
        client.headers['Authorization'] = 'Bearer '+token
        assert client.get('/api/v1/vision/frame').status_code == 204
        app.state.vision.cache.add({'sequence': 1, 'captured_at': time.time(), 'faces': [], 'jpeg_base64': 'test'})
        assert client.get('/api/v1/vision/frame').json()['sequence'] == 1
        assert client.get('/api/v1/vision/frame?after=1').status_code == 204
        assert client.post('/api/v1/vision/catalogue', json={'action': 'enroll', 'track_id': 1}).status_code == 409
        for command in ({'action': 'associate', 'track_id': 1}, {'action': 'enroll'},
                        {'action': 'rename', 'identity_id': 'FACE-TEST', 'name': ' '}):
            assert client.post('/api/v1/vision/catalogue', json=command).status_code == 422
        assert 'embeddings' not in client.get('/api/v1/vision/catalogue').text
        assert client.post('/api/v1/vision/start', json={'root': str(tmp_path)}).status_code == 422
        assert client.post('/api/v1/vision/start', json={'camera': -1}).status_code == 422
        assert client.post('/api/v1/vision/start', json={'heading': 360}).status_code == 422
        assert client.post('/api/v1/vision/stop').status_code == 200
        assert client.get('/api/v1/vision/frame').status_code == 204


def test_camera_settings_route_and_visual_audio_separation(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=str(tmp_path)), autostart=False)
    captured = []
    monkeypatch.setattr(app.state.vision, 'start', lambda *args: captured.append(args))
    with TestClient(app, base_url='http://127.0.0.1') as client:
        result = client.post('/api/v1/vision/start', json={'camera': 1, 'heading': 90, 'identity': True})
        assert result.status_code == 200
        assert captured[0] == (str(Path.home()/'ARGOS'), 1, 90., True)
        with client.websocket_connect('ws://127.0.0.1/ws/live') as ws:
            frame = ws.receive_json()
            assert frame['vision']['fov_deg'] == 78
            assert 'vision' in frame and 'integrations' in frame


@pytest.mark.parametrize('identity_enabled', [False, True])
def test_worker_projects_detected_face_and_optional_catalogue_id(tmp_path, monkeypatch, identity_enabled):
    """Exercise the worker with synthetic pixels and model doubles, without a camera/biometrics."""
    (tmp_path/'config').mkdir()
    (tmp_path/'config/default.yaml').write_text('synthetic test configuration')
    (tmp_path/'detector.onnx').touch()
    (tmp_path/'identity.onnx').touch()
    config = {'detection': {'model_path': 'detector.onnx'}, 'tracking': {},
              'identity': {'model_path': 'identity.onnx'}}
    stopped = Event()
    box = SimpleNamespace(x=60, y=20, width=30, height=40, center=SimpleNamespace(x=75, y=40))
    target = SimpleNamespace(track_id=1, raw_box=box, box=box, normalized_x=.75)

    class Camera:
        def __init__(self, *args):
            self.closed = False

        def open(self):
            return self

        def read(self):
            time.sleep(.002)
            return SimpleNamespace(left=np.zeros((100, 100, 3), dtype=np.uint8))

        def close(self):
            self.closed = True

    class Recognizer:
        def __init__(self, *args):
            self.templates = {'FACE-TEST': {'display_name': 'Synthetic identity', 'category': 'Unknown', 'embeddings': [[]]}}

        def identify(self, vector):
            return 'FACE-TEST', .9

        def suggestion(self, vector):
            return 'FACE-TEST', False, .9

    class Worker:
        def __init__(self, *args, **kwargs):
            self.pending = set()

        def submit(self, *args):
            return True

        def drain(self):
            return [(1, np.ones(2), None)]

        def close(self):
            pass

    def encode(*args):
        stopped.set()
        return True, np.array([0, 1, 2], dtype=np.uint8)

    modules = {
        'cv2': SimpleNamespace(setNumThreads=lambda n: None, imencode=encode, IMWRITE_JPEG_QUALITY=1),
        'yaml': SimpleNamespace(safe_load=lambda text: config),
        'argos.camera': SimpleNamespace(SingleCamera=Camera),
        'argos.detection.yunet': SimpleNamespace(YuNetFaceDetector=lambda *a, **kw: SimpleNamespace(detect_faces=lambda img: [(box, .9, [])])),
        'argos.tracking': SimpleNamespace(CentroidTracker=lambda *a: SimpleNamespace(update=lambda *a: [target])),
        'argos.identity.arcface': SimpleNamespace(ArcFaceRecognizer=Recognizer),
        'argos.identity.worker': SimpleNamespace(EmbeddingWorker=Worker),
    }
    for key, value in modules.items():
        monkeypatch.setitem(sys.modules, key, value)
    monkeypatch.setattr(sys, 'path', list(sys.path))

    class Packets(Queue):
        def cancel_join_thread(self):
            pass

    packets = Packets(maxsize=3)
    camera_worker(str(tmp_path), 0, 90, identity_enabled, packets, Queue(), stopped)
    catalogue, packet = packets.get_nowait(), packets.get_nowait()
    assert 'catalogue' in catalogue
    face = packet['faces'][0]
    assert face['bearing_deg'] == pytest.approx(face_bearing(.75, 90))
    assert face['box'] == [.6, .2, .3, .4]
    assert face['identity_id'] == ('FACE-TEST' if identity_enabled else None)
    assert face['source_of_sound_confirmed'] is False
    assert 'distance' not in face and 'embeddings' not in face
