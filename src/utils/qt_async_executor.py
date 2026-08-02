"""Qt Async Executor - Integration propre asyncio/Qt pour Windows.

Utilise qasync si disponible, sinon fallback sur QEventLoop personnalise.
Resout le probleme de l'event loop ProactorEventLoop vs Qt sur Windows.
"""
from __future__ import annotations

import asyncio
import sys
import logging
from typing import Optional, Callable, Any, Awaitable, TypeVar
from functools import partial

from PySide6.QtCore import QObject, QTimer, QCoreApplication, Signal, Slot

logger = logging.getLogger(__name__)

T = TypeVar('T')

_HAS_QASYNC = False
try:
    import qasync
    _HAS_QASYNC = True
except ImportError:
    pass


class QtAsyncExecutor(QObject):
    """Executor centralise pour taches asyncio dans l'application Qt.
    
    Garantit :
    - Un seul event loop asyncio partage avec Qt
    - Nettoyage automatique des taches a l'arret
    - Thread-safety pour callbacks cross-thread
    - Integration avec le cycle de vie QApplication
    """
    
    # Signal pour executer des coroutines depuis n'importe quel thread
    run_coro_signal = Signal(object)  # (coroutine_factory, future)
    
    _instance: Optional['QtAsyncExecutor'] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _qasync_loop: Optional[Any] = None
    _running = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        super().__init__()
        self._initialized = True
        self._pending_tasks: set[asyncio.Task] = set()
        self._shutdown_callbacks: list[Callable] = []
        self._qt_timer: Optional[QTimer] = None
        self.run_coro_signal.connect(self._execute_coro)
        
    @classmethod
    def initialize(cls, app: QCoreApplication = None) -> 'QtAsyncExecutor':
        """Initialise l'executor avec l'application Qt.
        
        Doit etre appele une seule fois au demarrage de l'app.
        """
        instance = cls()
        if instance._running:
            return instance
            
        if _HAS_QASYNC:
            # qasync gere l'integration automatiquement
            instance._qasync_loop = qasync.QEventLoop(app or QCoreApplication.instance())
            asyncio.set_event_loop(instance._qasync_loop)
            instance._loop = instance._qasync_loop
            logger.info("Async executor initialise avec qasync")
        else:
            # Fallback: creer un event loop compatible
            if sys.platform == 'win32':
                # Sur Windows, utiliser ProactorEventLoop pour subprocess/bleak
                instance._loop = asyncio.ProactorEventLoop()
            else:
                instance._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(instance._loop)
            # Timer pour pomper l'asyncio loop depuis Qt
            instance._qt_timer = QTimer()
            instance._qt_timer.setInterval(10)  # 100Hz
            instance._qt_timer.timeout.connect(instance._pump_asyncio)
            instance._qt_timer.start()
            logger.info("Async executor initialise avec fallback timer")
            
        instance._running = True
        return instance
    
    def _pump_asyncio(self):
        """Pompe l'event loop asyncio depuis le timer Qt."""
        if self._loop and self._running:
            try:
                self._loop.call_soon(self._loop.stop)
                self._loop.run_forever()
            except Exception as e:
                logger.error("Erreur pump asyncio: %s", e)
    
    @classmethod
    def get_loop(cls) -> asyncio.AbstractEventLoop:
        """Retourne l'event loop asyncio partage."""
        if cls._instance and cls._instance._loop:
            return cls._instance._loop
        raise RuntimeError("QtAsyncExecutor non initialise. Appelez initialize() d'abord.")
    
    @classmethod
    def instance(cls) -> 'QtAsyncExecutor':
        if cls._instance is None:
            raise RuntimeError("QtAsyncExecutor non initialise")
        return cls._instance
    
    def create_task(self, coro: Awaitable[T], name: str = None) -> asyncio.Task[T]:
        """Cree une tache asyncio trackee centralement.
        
        La tache est automatiquement nettoyee a la completion ou a l'arret.
        """
        loop = self.get_loop()
        task = loop.create_task(coro)
        if name:
            task.set_name(name)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
        # Log exceptions non capturees
        task.add_done_callback(self._log_task_exception)
        return task
    
    def _log_task_exception(self, task: asyncio.Task):
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            logger.error("Tache async echouee: %s", exc, exc_info=exc)
            try:
                from src.utils.error_manager import error_manager
                from src.utils.error_types import ErrorCategory
                error_manager.error(
                    category=ErrorCategory.APPLICATION,
                    error_type="async_task_error",
                    message=f"Erreur d'arriere-plan: {exc}"
                )
            except Exception:
                pass
    
    def run_coro_threadsafe(self, coro_factory: Callable[[], Awaitable[T]]) -> asyncio.Future:
        """Execute une coroutine depuis n'importe quel thread (thread-safe).
        
        Utilise un signal Qt pour marshaller l'execution vers le thread principal.
        Retourne un Future asyncio qu'on peut awaiter.
        """
        future: asyncio.Future = asyncio.Future()
        self.run_coro_signal.emit((coro_factory, future))
        return future
    
    @Slot(object)
    def _execute_coro(self, payload: tuple):
        """Slot interne execute dans le thread Qt principal."""
        coro_factory, future = payload
        try:
            coro = coro_factory()
            task = self.create_task(coro)
            # Chain result to future
            def _done(t: asyncio.Task):
                if future.cancelled():
                    return
                if t.cancelled():
                    future.cancel()
                elif t.exception():
                    future.set_exception(t.exception())
                else:
                    future.set_result(t.result())
            task.add_done_callback(_done)
        except Exception as e:
            if not future.done():
                future.set_exception(e)
    
    def register_shutdown(self, callback: Callable):
        """Enregistre un callback d'arret propre."""
        self._shutdown_callbacks.append(callback)
    
    async def shutdown(self):
        """Arret propre de toutes les taches."""
        self._running = False
        logger.info("Arret async executor: %d taches en cours", len(self._pending_tasks))
        
        # Appeler callbacks d'arret
        for cb in self._shutdown_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
            except Exception as e:
                logger.error("Erreur shutdown callback: %s", e)
        
        # Annuler toutes les taches en attente
        for task in list(self._pending_tasks):
            if not task.done():
                task.cancel()
        
        # Attendre completion (max 3s)
        if self._pending_tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._pending_tasks, return_exceptions=True),
                    timeout=3.0
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout arret taches async")
        
        self._pending_tasks.clear()
        
        if self._qt_timer:
            self._qt_timer.stop()
        if self._qasync_loop:
            self._qasync_loop.close()
        elif self._loop:
            self._loop.close()
        
        logger.info("Async executor arrete")


# Helpers pratiques
def create_task(coro: Awaitable[T], name: str = None) -> asyncio.Task[T]:
    """Shortcut pour QtAsyncExecutor.instance().create_task()"""
    return QtAsyncExecutor.instance().create_task(coro, name)

def run_coro_threadsafe(coro_factory: Callable[[], Awaitable[T]]) -> asyncio.Future:
    """Shortcut pour QtAsyncExecutor.instance().run_coro_threadsafe()"""
    return QtAsyncExecutor.instance().run_coro_threadsafe(coro_factory)

def get_async_loop() -> asyncio.AbstractEventLoop:
    """Shortcut pour QtAsyncExecutor.get_loop()"""
    return QtAsyncExecutor.get_loop()