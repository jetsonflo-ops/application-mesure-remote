"""Secure clear — Effacement memoire securise pour les secrets.

Utilise ctypes.memset (appel de librairie via ctypes = pas optimise
par le compilateur C).

Limitations :
  - Python str est IMMUTABLE. La memoire d'un str ne peut PAS etre
    effacee de maniere fiable. Utilisez bytearray pour les mots de passe.
  - Cette fonction agit sur bytearray, ctypes arrays, et tout type
    supportant le buffer protocol.
"""

import ctypes


def secure_clear(obj) -> None:
    """Efface le contenu d'un objet mutable supportant le buffer protocol.

    Appelle memset via ctypes — garanti de ne pas etre optimise.

    Args:
        obj: bytearray, ctypes.Array, ou tout objet mutable.

    Note:
        Ne PAS utiliser sur str (immuable).
    """
    try:
        if isinstance(obj, ctypes.Array):
            addr = ctypes.addressof(obj)
            length = ctypes.sizeof(obj)
        else:
            buf = (ctypes.c_ubyte * len(obj)).from_buffer(obj)
            addr = ctypes.addressof(buf)
            length = len(obj)
    except (TypeError, ValueError):
        return
    if length > 0:
        ctypes.memset(addr, 0, length)


def secure_clear_string(s: str) -> str:
    """Tente d'effacer une str Python de la memoire.

    AVERTISSEMENT : Python str est IMMUTABLE. Cette fonction ne peut
    PAS garantir que la memoire est effacee.

    Returns:
        Toujours "" (empty string).
    """
    if not isinstance(s, str) or len(s) == 0:
        return ""
    import gc
    gc.collect()
    return ""
