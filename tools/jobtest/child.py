import socket, time
s = socket.socket(); s.bind(("127.0.0.1", 8188)); s.listen(1)
with open(r"C:/Users/jun/Desktop/xieyi/web-launcher/tools/jobtest/child.alive", "w") as f:
    f.write("alive")
time.sleep(60)
