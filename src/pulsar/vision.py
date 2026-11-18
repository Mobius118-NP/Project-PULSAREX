"""Local ARGOS adapter: bounded video/metadata cache, no audio-to-person attribution."""
import base64
import math
import multiprocessing as mp
import sys
import time
from collections import deque
from pathlib import Path
from queue import Empty, Full, Queue
from threading import RLock, Thread


def face_bearing(normalized_x, heading=0., fov=78.):
    """Rectilinear camera projection. Image right is clockwise from optical axis."""
    if not 0 <= normalized_x <= 1 or not 0 < fov < 180:
        raise ValueError('Invalid face coordinate/FOV')
    return (heading+math.degrees(math.atan((2*normalized_x-1)*math.tan(math.radians(fov/2))))) % 360


class FrameCache:
    def __init__(self, capacity=8):
        self.frames = deque(maxlen=capacity)
        self.lock = RLock()

    def add(self, packet):
        with self.lock:
            self.frames.append(packet)

    def latest(self, now=None):
        with self.lock:
            if not self.frames:
                return None
            packet = dict(self.frames[-1])
        age = max(0, (time.time() if now is None else now)-packet['captured_at'])
        packet.update(age_seconds=age, stale=age > 1.)
        if packet['stale']:
            packet['faces'] = []
        return packet

    def clear(self):
        with self.lock:
            self.frames.clear()


def _latest_put(queue, item):
    try:
        queue.put_nowait(item)
    except Full:
        try:
            queue.get_nowait()
        except Empty:
            pass
        try:
            queue.put_nowait(item)
        except Full:
            pass


def camera_worker(root, camera, heading, identity_enabled, packets, commands, stopped):
    """Native camera/model calls are isolated from HTTP/audio and can be terminated."""
    capture = worker = None
    try:
        import cv2
        import yaml
        cv2.setNumThreads(1)
        sys.path.insert(0, str(Path(root)/'src'))
        from argos.camera import SingleCamera
        from argos.detection.yunet import YuNetFaceDetector
        from argos.tracking import CentroidTracker
        root = Path(root)
        cfg = yaml.safe_load((root/'config/default.yaml').read_text(encoding='utf-8'))
        detection, tracking = cfg['detection'], cfg['tracking']
        model = root/detection['model_path']
        if not model.is_file():
            raise RuntimeError(f'ARGOS YuNet weights missing: {model}. Install weights using ARGOS setup first.')
        detector = YuNetFaceDetector(model, detection.get('score_threshold', .8),
                                    detection.get('nms_threshold', .3), input_size=320)
        tracker = CentroidTracker(tracking.get('max_center_distance_px', 90), 3,
                                  tracking.get('ema_alpha', .3))
        recognition = None
        identity = cfg.get('identity', {})
        identity_status = 'disabled'
        if identity_enabled:
            weights, templates = root/identity.get('model_path', 'models/w600k_r50.onnx'), root/identity.get('templates_path', 'data/face_templates.json')
            if weights.is_file():
                from argos.identity.arcface import ArcFaceRecognizer
                from argos.identity.worker import EmbeddingWorker
                recognition = ArcFaceRecognizer(weights, templates, identity.get('similarity_threshold', .45),
                                                 identity.get('suggestion_threshold', .37), identity.get('ambiguity_margin', .04))
                worker = EmbeddingWorker(recognition, max_queue=4)
                identity_status = 'Recognition ready; local catalogue loaded; no automatic enrollment'
            else:
                identity_status = 'Recognition weights missing; faces remain Unknown'
        captured = Queue(maxsize=2)
        capture = SingleCamera(camera, 640, 480, 30).open()

        def acquire():
            while not stopped.is_set():
                frame = capture.read()
                if frame is None:
                    _latest_put(captured, (None, time.time()))
                    return
                image = frame.left
                if image.shape[1] > 640:
                    image = cv2.resize(image, (640, round(image.shape[0]*640/image.shape[1])))
                _latest_put(captured, (image, time.time()))
        Thread(target=acquire, daemon=True, name='argos-latest-camera').start()
        sequence, next_detect = 0, 0.
        targets, known, last_identity, embeddings = [], {}, {}, {}
        observed_at = 0.
        def catalogue(message=''):
            rows = [{'identity_id': key, 'display_name': value['display_name'], 'category': value['category'],
                     'template_count': len(value['embeddings'])} for key, value in recognition.templates.items()] if recognition else []
            _latest_put(packets, {'catalogue': rows[:512], 'command_status': message})
        catalogue()
        while not stopped.is_set():
            try:
                command = commands.get_nowait()
            except Empty:
                command = None
            if command:
                try:
                    if not recognition:
                        raise ValueError('Enable existing-catalogue recognition with ArcFace weights first')
                    action, identity_id = command['action'], command.get('identity_id')
                    if action in ('enroll', 'associate'):
                        track = command.get('track_id')
                        if track not in embeddings or time.time()-observed_at > 1:
                            raise ValueError('No current embedding for that track; wait for recognition or select a visible track')
                        identity_id = recognition.enroll(embeddings[track], identity_id if action == 'associate' else None)
                        if command.get('name'):
                            recognition.update_identity(identity_id, display_name=command['name'])
                    elif action == 'rename':
                        recognition.update_identity(identity_id, display_name=command['name'])
                    elif action == 'category':
                        recognition.update_identity(identity_id, category=command['category'])
                    elif action == 'delete':
                        recognition.delete_identity(identity_id)
                    known.clear()
                    last_identity.clear()
                    catalogue(action+' completed')
                except (ValueError, KeyError, OSError) as exc:
                    catalogue(str(exc))
            try:
                image, stamp = captured.get(timeout=.25)
            except Empty:
                continue
            if image is None:
                raise RuntimeError('Camera disconnected or stopped delivering frames')
            now = time.monotonic()
            height, width = image.shape[:2]
            if now >= next_detect:
                detections = detector.detect_faces(image)[:32]
                targets = tracker.update([box for box, _, _ in detections], (width, height))
                # Missed tracks are hidden, not displayed as new observations.
                targets = [t for t in targets if any(abs(t.raw_box.center.x-b.center.x)<1 and
                           abs(t.raw_box.center.y-b.center.y)<1 for b, _, _ in detections)]
                observed_at = stamp
                active = {t.track_id for t in targets}
                known = {k: v for k, v in known.items() if k in active}
                last_identity = {k: v for k, v in last_identity.items() if k in active}
                embeddings = {k: v for k, v in embeddings.items() if k in active}
                if worker:
                    for box, _, landmarks in detections[:16]:
                        target = min(targets, key=lambda t: abs(t.raw_box.center.x-box.center.x)+abs(t.raw_box.center.y-box.center.y), default=None)
                        if target and now-last_identity.get(target.track_id, -10) > 1.5:
                            if worker.submit(target.track_id, image, landmarks):
                                last_identity[target.track_id] = now
                next_detect = now+.1  # Detection 10 Hz, capture/display independently up to 30 Hz.
            if worker:
                for track_id, vector, error in worker.drain():
                    worker.pending.discard(track_id)
                    if error or track_id not in {t.track_id for t in targets}:
                        continue
                    embeddings[track_id] = vector
                    _, ambiguous, _ = recognition.suggestion(vector)
                    identity_id, score = recognition.identify(vector)
                    if identity_id and not ambiguous:
                        known[track_id] = (identity_id, recognition.templates[identity_id]['display_name'], score)
                    else:
                        known.pop(track_id, None)
            faces = []
            for target in targets[:32]:
                identity_id, name, confidence = known.get(target.track_id, (None, 'Unknown', None))
                box = target.box
                faces.append({'track_id': target.track_id, 'normalized_x': target.normalized_x,
                              'bearing_deg': face_bearing(target.normalized_x, heading),
                              'box': [box.x/width, box.y/height, box.width/width, box.height/height],
                              'identity_id': identity_id, 'identity_label': name,
                              'identity_similarity': confidence, 'observed_at': observed_at,
                              'modality': 'visual', 'source_of_sound_confirmed': False})
            ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 72])
            if ok:
                sequence += 1
                _latest_put(packets, {'sequence': sequence, 'captured_at': stamp, 'faces': faces,
                                     'width': width, 'height': height, 'jpeg_base64': base64.b64encode(encoded).decode('ascii'),
                                     'camera_heading_deg': heading, 'fov_deg': 78., 'identity_status': identity_status})
    except Exception as exc:
        _latest_put(packets, {'error': str(exc)[:1000]})
    finally:
        if capture:
            capture.close()
        if worker:
            worker.close()
        packets.cancel_join_thread()


class VisionService:
    def __init__(self):
        self.cache = FrameCache()
        self.process = self.stop_event = self.packets = None
        self.error = None
        self.catalogue = []
        self.command_status = ''
        self.lock = RLock()

    def start(self, root, camera=0, heading=0., identity=False):
        with self.lock:
            if self.process is not None:
                raise ValueError('Stop ARGOS before changing camera settings')
            if not (Path(root)/'src/argos').is_dir():
                raise ValueError('Select the existing ARGOS project folder')
            if type(camera) is not int or not 0 <= camera <= 32 or not math.isfinite(heading) or not 0 <= heading < 360:
                raise ValueError('Invalid camera index or heading')
            self.cache.clear()
            self.error = None
            self.catalogue = []
            self.command_status = ''
            context = mp.get_context('spawn')
            self.stop_event, self.packets = context.Event(), context.Queue(maxsize=3)
            self.commands = context.Queue(maxsize=8)
            self.process = context.Process(target=camera_worker, args=(str(root), camera, heading, identity,
                                            self.packets, self.commands, self.stop_event), name='argos-server-camera', daemon=True)
            self.process.start()
            self.relay_thread = Thread(target=self._relay, args=(self.process, self.packets, self.stop_event), daemon=True)
            self.relay_thread.start()

    def _relay(self, process, packets, stopped):
        last_frame = time.monotonic()
        while not stopped.is_set():
            try:
                packet = packets.get(timeout=.25)
            except Empty:
                if not process.is_alive():
                    self.error = self.error or 'ARGOS camera worker exited'
                    break
                if time.monotonic()-last_frame > 30:
                    self.error = 'Camera/model startup timed out; Stop and retry'
                    stopped.set()
                    break
                continue
            except (EOFError, OSError, ValueError):
                break
            if 'error' in packet:
                self.error = packet['error']
                break
            if stopped.is_set():
                break
            if 'catalogue' in packet:
                self.catalogue = packet['catalogue']
                self.command_status = packet['command_status']
                continue
            self.cache.add(packet)
            last_frame = time.monotonic()

    def status(self):
        packet = self.cache.latest()
        return {'running': bool(self.process and self.process.is_alive() and not self.error),
                'error': self.error, 'fov_deg': 78., 'frame_age_seconds': packet['age_seconds'] if packet else None,
                'stale': packet is None or packet['stale'], 'faces': packet['faces'] if packet else [],
                'camera_heading_deg': packet.get('camera_heading_deg', 0) if packet else 0,
                'identity_status': packet.get('identity_status', 'Not active') if packet else 'Not active'}

    def command(self, data):
        if not self.process or not self.process.is_alive() or self.error:
            raise ValueError('Start the camera with recognition enabled first')
        try:
            self.commands.put_nowait(data)
        except Full as exc:
            raise ValueError('Catalogue command queue is busy; retry shortly') from exc

    def stop(self):
        with self.lock:
            if self.process:
                self.stop_event.set()
                self.process.join(timeout=2)
                if self.process.is_alive():
                    self.process.terminate()
                    self.process.join(timeout=2)
                self.process = None
                self.relay_thread.join(timeout=1)
                self.packets.close()
                self.packets.cancel_join_thread()
                self.commands.close()
                self.commands.cancel_join_thread()
            self.cache.clear()
            self.catalogue = []
            self.error = None
