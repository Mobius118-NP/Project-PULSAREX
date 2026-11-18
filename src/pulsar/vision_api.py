import asyncio
from pathlib import Path
from typing import Literal

from fastapi import HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CameraSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    root: str = Field(default_factory=lambda: str(Path.home()/'ARGOS'), max_length=1024)
    camera: int = Field(default=0, ge=0, le=32)
    heading: float = Field(default=0., ge=0, lt=360)
    identity: bool = False


class CatalogueCommand(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['enroll', 'associate', 'rename', 'category', 'delete']
    identity_id: str | None = Field(default=None, max_length=64)
    track_id: int | None = Field(default=None, ge=1)
    name: str = Field(default='', max_length=120)
    category: Literal['Friendly', 'Unknown'] = 'Unknown'

    @model_validator(mode='after')
    def require_selected_identity_and_track(self):
        if self.action in ('associate', 'rename', 'category', 'delete') and not self.identity_id:
            raise ValueError('Select a saved identity first')
        if self.action in ('enroll', 'associate') and self.track_id is None:
            raise ValueError('Select a visible track first')
        if self.action == 'rename' and not self.name.strip():
            raise ValueError('Enter a nonempty display name')
        return self


def install_vision_api(app, vision):
    @app.get('/api/v1/vision')
    def status():
        return {**vision.status(), 'default_root': str(Path.home()/'ARGOS'),
                'identity_policy': 'Existing enrolled identities only; no automatic enrollment or audio attribution'}

    @app.post('/api/v1/vision/start')
    async def start(body: CameraSettings):
        if Path(body.root).resolve() != (Path.home()/'ARGOS').resolve():
            raise HTTPException(422, 'The server loads only the local user ARGOS project')
        try:
            await asyncio.to_thread(vision.start, body.root, body.camera, body.heading, body.identity)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return vision.status()

    @app.post('/api/v1/vision/stop')
    async def stop():
        await asyncio.to_thread(vision.stop)
        return vision.status()

    @app.get('/api/v1/vision/frame')
    def frame(after: int = Query(-1, ge=-1)):
        packet = vision.cache.latest()
        if packet is None or packet['sequence'] <= after:
            return Response(status_code=204)
        return packet

    @app.get('/api/v1/vision/catalogue')
    def catalogue():
        return {'identities': list(vision.catalogue), 'command_status': vision.command_status}

    @app.post('/api/v1/vision/catalogue', status_code=202)
    def command(body: CatalogueCommand):
        try:
            vision.command(body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'queued': True}
