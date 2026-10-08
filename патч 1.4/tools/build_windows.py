"""Build the Windows distribution on Windows; no project config files are copied."""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'vosk-model-small-ru-0.22'
BUILD_ROOT = Path(tempfile.gettempdir()) / 'NaryadAI-windows'
BUILD = BUILD_ROOT / 'build'
DIST = BUILD_ROOT / 'dist'


def main():
    if sys.platform != 'win32':
        raise SystemExit('Windows EXE must be built on Windows.')
    from PIL import Image
    BUILD.mkdir(parents=True, exist_ok=True)
    os.environ['NARYADAI_BUILD_DIR'] = str(BUILD)
    with Image.open(ROOT / 'web/icons/icon-512.png') as image:
        image.save(BUILD / 'naryadai.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    models = ROOT / 'voice_models'
    models.mkdir(exist_ok=True)
    if not (models / MODEL / 'am/final.mdl').is_file():
        archive = BUILD / (MODEL + '.zip')
        urllib.request.urlretrieve('https://alphacephei.com/vosk/models/' + MODEL + '.zip', archive)
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                destination = (models / item.filename).resolve()
                if not destination.is_relative_to(models.resolve()):
                    raise ValueError('Unsafe path in voice model archive')
            source.extractall(models)
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(DIST), '--workpath', str(BUILD / 'pyinstaller'),
                    str(ROOT / 'packaging/windows.spec')], cwd=ROOT, check=True)
    runtime = DIST / 'NaryadAI'
    shutil.copy2(runtime / 'NaryadAI.exe', runtime / 'NaryadAI-AI.exe')
    shutil.copy2(runtime / 'NaryadAI.exe', runtime / 'NaryadAI-Diagnostics.exe')
    forbidden = {'client_config.json', 'server_config.json', 'worker_config.json', '.env', 'naryadai.db'}
    assert not any(path.name in forbidden for path in runtime.rglob('*')), 'Private settings in distribution'
    for name in ('NaryadAI.exe', 'NaryadAI-AI.exe', 'NaryadAI-Diagnostics.exe'):
        result = BUILD / (name + '.smoke.json')
        process = subprocess.run([str(runtime / name), '--smoke-test', str(result)], cwd=BUILD, timeout=120)
        if process.returncode or not result.is_file():
            raise RuntimeError(f'{name} failed its frozen Windows smoke test')
        print(result.read_text(encoding='utf-8'), flush=True)
    archive = DIST / 'NaryadAI-Portable-1.8.1.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(runtime.rglob('*')):
            if path.is_file():
                output.write(path, path.relative_to(DIST))
    iscc = shutil.which('ISCC')
    if not iscc:
        for path in (Path('C:/Program Files (x86)/Inno Setup 6/ISCC.exe'), Path('C:/Program Files/Inno Setup 6/ISCC.exe')):
            if path.is_file():
                iscc = str(path)
                break
    if not iscc:
        raise RuntimeError('Install Inno Setup 6 to build the installer.')
    subprocess.run([iscc, '/DDistributionDir=' + str(DIST), '/DIconFile=' + str(BUILD / 'naryadai.ico'),
                    '/O' + str(DIST), str(ROOT / 'packaging/installer.iss')], cwd=ROOT, check=True)
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        # Isolated runner only: don't alter a developer's installed app/registry.
        installed = BUILD_ROOT / 'installed'
        subprocess.run([str(DIST / 'NaryadAI-Setup-1.8.1.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                        '/NORESTART', '/SP-', '/DIR=' + str(installed)], check=True, timeout=120)
        for name in ('NaryadAI.exe', 'NaryadAI-AI.exe', 'NaryadAI-Diagnostics.exe'):
            result = BUILD / ('installed-' + name + '.smoke.json')
            process = subprocess.run([str(installed / name), '--smoke-test', str(result)], cwd=BUILD, timeout=120)
            if process.returncode or not result.is_file():
                raise RuntimeError(f'Installed {name} failed its smoke test')
            print(result.read_text(encoding='utf-8'), flush=True)
        saved = Path(os.environ['LOCALAPPDATA']) / 'NaryadAI/config/client_config.json'
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_text('{"server":"https://example.com"}', encoding='utf-8')
        subprocess.run([str(installed / 'unins000.exe'), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'], check=True, timeout=120)
        for _ in range(40):
            if not (installed / 'NaryadAI.exe').exists():
                break
            time.sleep(0.25)
        assert not (installed / 'NaryadAI.exe').exists(), 'Uninstaller failed'
        assert saved.read_text(encoding='utf-8') == '{"server":"https://example.com"}', 'Uninstaller removed user settings'
        saved.unlink()
        (BUILD / 'installer.smoke.json').write_text('{"ok":true,"install":true,"uninstall":true,"settings_preserved":true}', encoding='utf-8')
    files = [DIST / 'NaryadAI-Setup-1.8.1.exe', archive]
    (DIST / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in files), encoding='utf-8')
    (ROOT / 'dist').mkdir(exist_ok=True)
    for path in files + [DIST / 'SHA256SUMS.txt']:
        shutil.copy2(path, ROOT / 'dist' / path.name)
    checks = ROOT / 'build/windows'
    checks.mkdir(parents=True, exist_ok=True)
    for path in BUILD.glob('*.smoke.json'):
        shutil.copy2(path, checks / path.name)


if __name__ == '__main__':
    main()
