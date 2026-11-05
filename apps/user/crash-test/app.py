import sys
print("启动到一半炸了: 演示用的故意崩溃")
sys.stderr.write("Traceback: 故意制造的非零退出
")
sys.exit(42)
