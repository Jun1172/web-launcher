import ctypes, os, subprocess, sys, time
kernel32 = ctypes.windll.kernel32
class IO(ctypes.Structure): _fields_=[(n,ctypes.c_uint64) for n in ("a","b","c","d","e","f")]
class BLI(ctypes.Structure): _fields_=[("t1",ctypes.c_longlong),("t2",ctypes.c_longlong),("flags",ctypes.c_uint32),("m1",ctypes.c_size_t),("m2",ctypes.c_size_t),("apl",ctypes.c_uint32),("aff",ctypes.c_size_t),("pri",ctypes.c_uint32),("sc",ctypes.c_uint32)]
class ELI(ctypes.Structure): _fields_=[("b",BLI),("io",IO),("pm",ctypes.c_size_t),("jm",ctypes.c_size_t),("pp",ctypes.c_size_t),("pj",ctypes.c_size_t)]
job = kernel32.CreateJobObjectW(None, None)
info = ELI(); info.b.flags = 0x2000
ok1 = kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
p = subprocess.Popen([sys.executable, os.path.join(os.path.dirname(__file__), "child.py")])
h = kernel32.OpenProcess(0x0100|0x0001, False, p.pid)
ok2 = kernel32.AssignProcessToJobObject(job, h)
print(f"create={bool(job)} setinfo={bool(ok1)} open={bool(h)} assign={bool(ok2)} lasterr={ctypes.GetLastError()} childpid={p.pid}", flush=True)
time.sleep(45)
