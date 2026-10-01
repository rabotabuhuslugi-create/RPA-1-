# Установка на Windows (PowerShell)

Команды выполняйте в обычном PowerShell (не cmd).

## 1. Python, Git, Tesseract
```powershell
winget install -e --id Python.Python.3.12
winget install -e --id Git.Git
winget install -e --id UB-Mannheim.TesseractOCR
```
После установки **закройте и снова откройте PowerShell**, затем проверьте:
```powershell
python --version
git --version
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```
В списке должен быть `rus`. Если его нет, скачайте `rus.traineddata` со страницы
https://github.com/tesseract-ocr/tessdata и положите в `C:\Program Files\Tesseract-OCR\tessdata`
(PowerShell от имени администратора).

## 2. Poppler (нужен только для PDF)
Скачайте архив Release с https://github.com/oschwartz10612/poppler-windows/releases,
распакуйте, например, в `C:\poppler`. Путь к `bin` пропишете в конфиге.
(Либо через Scoop: `scoop install poppler`.)

## 3. Код проекта
```powershell
git clone https://github.com/rabotabuhuslugi-create/RPA-1-.git C:\RPA-1C
cd C:\RPA-1C
git checkout claude/rpa-1c-document-upload-rlsoyl
```

## 4. Виртуальное окружение и зависимости
```powershell
python -m venv .venv
# если появится ошибка о политике выполнения скриптов:
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 5. Конфиг
```powershell
Copy-Item config.example.yaml config.yaml
notepad config.yaml
```
Заполните: `base_url`, `user`, `own_inn`, `organization_key`, а также пути:
```yaml
ocr:
  tesseract_cmd: 'C:\Program Files\Tesseract-OCR\tesseract.exe'
  poppler_path: 'C:\poppler\Library\bin'   # путь к папке с pdftoppm.exe
```
Пути пишите в одинарных кавычках.

## 6. Пароль 1С (не хранить в файле)
Только на текущую сессию:
```powershell
$env:ONEC_PASSWORD = "ваш_пароль"
```
Постоянно для вашего пользователя Windows:
```powershell
[Environment]::SetEnvironmentVariable("ONEC_PASSWORD", "ваш_пароль", "User")
```
(после этого откройте новое окно PowerShell)

## 7. Проверка и запуск
```powershell
pytest                              # тест парсера
# положите сканы в C:\RPA-1C\inbox
python -m rpa1c.main --dry-run      # только OCR, 1С не трогаем
python -m rpa1c.main                # боевой режим
```

## 8. Автозапуск (Планировщик заданий)
Одноразовый проход каждые 15 минут — поставьте в config.yaml `poll_seconds: 0` и создайте задачу:
```powershell
$a = New-ScheduledTaskAction -Execute "C:\RPA-1C\.venv\Scripts\python.exe" `
     -Argument "-m rpa1c.main" -WorkingDirectory "C:\RPA-1C"
$t = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "RPA-1C-Scans" -Action $a -Trigger $t
```
Переменная `ONEC_PASSWORD` должна быть задана на уровне пользователя (п. 6), под которым выполняется задача.
