import subprocess, sys, os

PACKAGES_DIR = '/tmp/packages'
os.makedirs(PACKAGES_DIR, exist_ok=True)

# pip이 .local 폴더 접근 시도할 때 /tmp로 리디렉트
env = os.environ.copy()
env['HOME'] = '/tmp'
env['PIP_NO_USER_SITE'] = '1'
env['PYTHONUSERBASE'] = '/tmp/pyuser'

print("[bootstrap] 패키지 설치 중...")
result = subprocess.run([
    sys.executable, '-m', 'pip', 'install',
    '-r', 'requirements.txt',
    '--target', PACKAGES_DIR,
    '--isolated',
    '-q'
], env=env)

if result.returncode != 0:
    print("[bootstrap] pip 실패, prefix 방식으로 재시도...")
    subprocess.run([
        sys.executable, '-m', 'pip', 'install',
        '-r', 'requirements.txt',
        '--prefix=/tmp/pyuser',
        '--isolated', '-q'
    ], env=env)
    sys.path.insert(0, '/tmp/pyuser/lib/python{}.{}/site-packages'.format(*sys.version_info[:2]))
else:
    print("[bootstrap] 설치 완료!")
    sys.path.insert(0, PACKAGES_DIR)

print("[bootstrap] 앱 시작...")
import runpy
runpy.run_path('main.py', run_name='__main__')
