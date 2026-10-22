import importlib
for name in ['docx', 'lxml']:
    try:
        importlib.import_module(name)
        print(f'{name}:ok')
    except Exception as exc:
        print(f'{name}:missing:{type(exc).__name__}')
