"""Commercial model and cross-process admission guards; no model downloads."""
try:
    import fcntl
except ImportError:
    fcntl = None
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from core import ac_audio_studio as studio
from fastapi import HTTPException

@unittest.skipIf(fcntl is None, "Audio Studio requires POSIX render leases")
class AudioStudioPolicyTests(unittest.TestCase):
    def test_normal_application_keeps_its_model_choices(self):
        with patch.dict(os.environ,{'AC_AUDIO_STUDIO':'0'}):
            self.assertEqual(studio.require_model('k2-fsa/OmniVoice'),'k2-fsa/OmniVoice')

    def test_commercial_profile_rejects_noncommercial_and_unknown_weights(self):
        with patch.dict(os.environ,{'AC_AUDIO_STUDIO':'1'}):
            for repo in ['k2-fsa/OmniVoice','facebook/mms-tts-eng','unknown/voice']:
                with self.assertRaises(ValueError):studio.require_model(repo)
            for repo in studio.ALLOWED_MODELS:self.assertEqual(studio.require_model(repo),repo)

    def test_active_audiobook_prevents_a_new_model_job(self):
        with patch.dict(os.environ,{'AC_AUDIO_STUDIO':'1'}),patch.object(studio,'audiobook_active',return_value=True):
            with self.assertRaises(HTTPException) as caught:
                with studio.resource_lease():self.fail('admitted while audiobook active')
            self.assertEqual(caught.exception.status_code,409)

    def test_independent_process_lease_prevents_overlapping_work(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'render.lock'
            with path.open('a+') as busy:
                fcntl.flock(busy,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.dict(os.environ,{'AC_AUDIO_STUDIO':'1','AC_AUDIO_RENDER_LOCK':str(path)}),patch.object(studio,'audiobook_active',return_value=False):
                    with self.assertRaises(HTTPException):
                        with studio.resource_lease():self.fail('admitted while another lease held')

    def test_low_memory_refuses_load_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'render.lock'
            with patch.dict(os.environ,{'AC_AUDIO_STUDIO':'1','AC_AUDIO_RENDER_LOCK':str(path)}),patch.object(studio,'audiobook_active',return_value=False),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=1024**3)):
                with self.assertRaises(HTTPException):
                    with studio.resource_lease():self.fail('admitted without headroom')
            with path.open('a+') as retry:fcntl.flock(retry,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_live_memory_readiness_uses_exact_admission_threshold(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'render.lock'
            for available,ready in [(studio.MIN_AVAILABLE_BYTES-1,False),(studio.MIN_AVAILABLE_BYTES,True)]:
                with self.subTest(available=available),patch.dict(os.environ,{'AC_AUDIO_RENDER_LOCK':str(path)}),patch.object(studio,'audiobook_active',return_value=False),patch('psutil.virtual_memory',return_value=SimpleNamespace(available=available)):
                    health=studio.status()
                self.assertEqual(health['available_bytes'],available)
                self.assertEqual(health['required_available_gb'],6)
                self.assertEqual(health['memory_ready'],ready)

    def test_disconnected_client_keeps_lease_until_native_work_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'render.lock';lease=path.open('a+')
            fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
            native_done=threading.Event()
            backend=SimpleNamespace(release_idle_engines=lambda seconds:None,reset_active_backend=lambda:None)
            mlx=SimpleNamespace(clear_cache=lambda:None)
            with patch.object(studio,'_native_busy',side_effect=lambda:not native_done.is_set()),patch.dict(sys.modules,{'services.tts_backend':backend,'mlx':SimpleNamespace(core=mlx),'mlx.core':mlx}):
                worker=threading.Thread(target=studio._release,args=(lease,));worker.start()
                with path.open('a+') as competing:
                    with self.assertRaises(BlockingIOError):fcntl.flock(competing,fcntl.LOCK_EX|fcntl.LOCK_NB)
                native_done.set();worker.join(timeout=3);self.assertFalse(worker.is_alive())
            with path.open('a+') as next_job:fcntl.flock(next_job,fcntl.LOCK_EX|fcntl.LOCK_NB)

if __name__=='__main__':unittest.main()
