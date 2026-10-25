import ctypes, fcntl, os, sys, time

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_SETUP = 0x405C5503
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN, EV_KEY = 0, 1
KEYS = dict(enter=28, up=103, down=108, left=105, right=106,
            x=45, z=44, esc=1, space=57, rshift=54, p=25)


class InputId(ctypes.Structure):
    _fields_ = [("bustype", ctypes.c_uint16), ("vendor", ctypes.c_uint16),
                ("product", ctypes.c_uint16), ("version", ctypes.c_uint16)]


class UinputSetup(ctypes.Structure):
    _fields_ = [("id", InputId), ("name", ctypes.c_char * 80),
                ("ff_effects_max", ctypes.c_uint32)]


class InputEvent(ctypes.Structure):
    _fields_ = [("sec", ctypes.c_long), ("usec", ctypes.c_long),
                ("type", ctypes.c_uint16), ("code", ctypes.c_uint16),
                ("value", ctypes.c_int32)]


fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
fcntl.ioctl(fd, UI_SET_EVBIT, EV_SYN)
for code in KEYS.values():
    fcntl.ioctl(fd, UI_SET_KEYBIT, code)

setup = UinputSetup()
setup.id.bustype = 0x03
setup.id.vendor = 0x1234
setup.id.product = 0x5678
setup.id.version = 1
setup.name = b"fakekbd"
fcntl.ioctl(fd, UI_DEV_SETUP, setup)
fcntl.ioctl(fd, UI_DEV_CREATE)
time.sleep(1.5)


def emit(t, c, v):
    os.write(fd, bytes(InputEvent(0, 0, t, c, v)))


def tap(code):
    emit(EV_KEY, code, 1)
    emit(EV_SYN, 0, 0)
    time.sleep(0.06)
    emit(EV_KEY, code, 0)
    emit(EV_SYN, 0, 0)
    time.sleep(0.12)


for name in (sys.argv[1:] or ["enter"]):
    tap(int(name) if name.isdigit() else KEYS[name])
    time.sleep(0.4)

time.sleep(0.3)
fcntl.ioctl(fd, UI_DEV_DESTROY)
os.close(fd)
print("sent", sys.argv[1:] or ["enter"])
