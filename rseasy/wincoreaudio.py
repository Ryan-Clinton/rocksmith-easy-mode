"""Just enough of the Windows Core Audio API to set a capture device's gain.

Plain ctypes COM: walk the active capture endpoints, match one by friendly
name, and talk to its IAudioEndpointVolume in dB. Windows only - import it
lazily. Every COM failure surfaces as OSError (the HRESULT return type
raises it), which the caller turns into a plain message.

Vtable indices below are fixed by the published interfaces (mmdeviceapi.h,
endpointvolume.h), counting IUnknown's three methods first.
"""
import ctypes
import uuid
from contextlib import contextmanager
from ctypes import POINTER, byref, c_float, c_int, c_uint, c_ulong, c_ushort, c_void_p

CLSCTX_ALL = 23
E_CAPTURE = 1
DEVICE_STATE_ACTIVE = 1
STGM_READ = 0
VT_LPWSTR = 31
COINIT_APARTMENTTHREADED = 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", c_ulong), ("Data2", c_ushort), ("Data3", c_ushort),
                ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, text):
        u = uuid.UUID(text)
        super().__init__(u.fields[0], u.fields[1], u.fields[2],
                         (ctypes.c_ubyte * 8)(*u.bytes[8:]))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", c_ulong)]


class PROPVARIANT(ctypes.Structure):
    # vt, three reserved words, then a 16-byte union (8 on 32-bit); only the
    # string pointer at its start is read.
    _fields_ = [("vt", c_ushort), ("r1", c_ushort), ("r2", c_ushort),
                ("r3", c_ushort), ("ptr", c_void_p), ("pad", c_void_p)]


CLSID_MMDeviceEnumerator = GUID("BCDE0395-E52F-467C-8E3D-C4579291692E")
IID_IMMDeviceEnumerator = GUID("A95664D2-9614-4F35-A746-DE8DB63617E6")
IID_IAudioEndpointVolume = GUID("5CDF2C82-841E-4546-9722-0CF74078229A")
PKEY_Device_FriendlyName = PROPERTYKEY(
    GUID("A45C254E-DF1C-4EFD-8020-67D146A850E0"), 14)


def _call(obj, index, argtypes, *args):
    """Call method *index* of COM object *obj*; raises OSError on failure."""
    vtbl = ctypes.cast(obj, POINTER(c_void_p))[0]
    fn = ctypes.cast(vtbl, POINTER(c_void_p))[index]
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)
    return proto(fn)(obj, *args)


def _release(obj):
    if obj:
        vtbl = ctypes.cast(obj, POINTER(c_void_p))[0]
        fn = ctypes.cast(vtbl, POINTER(c_void_p))[2]
        ctypes.WINFUNCTYPE(c_ulong, c_void_p)(fn)(obj)


class Volume:
    """An IAudioEndpointVolume, in dB."""

    def __init__(self, ptr):
        self.ptr = ptr

    def get_db(self):
        v = c_float()
        _call(self.ptr, 8, (POINTER(c_float),), byref(v))
        return v.value

    def set_db(self, db):
        _call(self.ptr, 6, (c_float, c_void_p), c_float(db), None)

    def get_range(self):
        lo, hi, inc = c_float(), c_float(), c_float()
        _call(self.ptr, 20, (POINTER(c_float),) * 3,
              byref(lo), byref(hi), byref(inc))
        return lo.value, hi.value


def _friendly_name(dev):
    store = c_void_p()
    _call(dev, 4, (c_ulong, POINTER(c_void_p)), STGM_READ, byref(store))
    try:
        pv = PROPVARIANT()
        _call(store, 5, (POINTER(PROPERTYKEY), POINTER(PROPVARIANT)),
              byref(PKEY_Device_FriendlyName), byref(pv))
        try:
            return ctypes.wstring_at(pv.ptr) if pv.vt == VT_LPWSTR else ""
        finally:
            ctypes.windll.ole32.PropVariantClear(byref(pv))
    finally:
        _release(store)


def capture_names():
    """Friendly names of every active recording device."""
    with _devices() as devs:
        return [name for name, _dev in devs]


@contextmanager
def find_capture_volume(name_part):
    """Yield a Volume for the first active capture device whose friendly name
    contains *name_part* (case-insensitive), or None if there is none."""
    with _devices() as devs:
        for name, dev in devs:
            if name_part.lower() in name.lower():
                vol = c_void_p()
                _call(dev, 3, (POINTER(GUID), c_ulong, c_void_p,
                               POINTER(c_void_p)),
                      byref(IID_IAudioEndpointVolume), CLSCTX_ALL, None,
                      byref(vol))
                try:
                    yield Volume(vol)
                finally:
                    _release(vol)
                return
        yield None


@contextmanager
def _devices():
    """Yield [(friendly name, IMMDevice)] for active capture endpoints."""
    ole32 = ctypes.windll.ole32
    # S_OK or S_FALSE mean this call owes a CoUninitialize; anything else
    # (already initialised in another mode) is fine to use as it is.
    hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
    held = []
    try:
        enum = c_void_p()
        ctypes.oledll.ole32.CoCreateInstance(
            byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
            byref(IID_IMMDeviceEnumerator), byref(enum))
        held.append(enum)
        coll = c_void_p()
        _call(enum, 3, (c_int, c_ulong, POINTER(c_void_p)),
              E_CAPTURE, DEVICE_STATE_ACTIVE, byref(coll))
        held.append(coll)
        count = c_uint()
        _call(coll, 3, (POINTER(c_uint),), byref(count))
        devs = []
        for i in range(count.value):
            dev = c_void_p()
            _call(coll, 4, (c_uint, POINTER(c_void_p)), i, byref(dev))
            held.append(dev)
            devs.append((_friendly_name(dev), dev))
        yield devs
    finally:
        for obj in reversed(held):
            _release(obj)
        if hr in (0, 1):
            ole32.CoUninitialize()
