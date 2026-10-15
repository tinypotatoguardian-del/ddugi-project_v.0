"""
Enzonic 환경에서 패키지를 /home/container/packages에 설치 후 앱 실행
"""
import subprocess, sys, os

PACKAGES_DIR = '/home/container/packages'
os.makedirs(PACKAGES_DIR, exist_ok=True)

print("[bootstrap] 패키지 설치 중...")
subprocess.run([
    sys.executable, '-m', 'pip', 'install',
    '-r', 'requirements.txt',
    '--target', PACKAGES_DIR,
    '-q', '--upgrade'
], check=True)

print("[bootstrap] 패키지 설치 완료, 앱 시작...")
if PACKAGES_DIR not in sys.path:
    sys.path.insert(0, PACKAGES_DIR)

# main 실행
import runpy
runpy.run_path('main.py', run_name='__main__')
