"""Explicit device policy: discovery is separate from model readiness."""
DEVICES = ('NPU', 'GPU', 'CPU')


def requested_device(value):
    if not isinstance(value, str) or value.upper() not in {'AUTO', *DEVICES}:
        raise ValueError('Выберите Авто, NPU, GPU или CPU')
    return value.upper()


def candidates(requested, capabilities):
    requested = requested_device(requested)
    order = DEVICES if requested == 'AUTO' else (requested,)
    return [device for device in order if capabilities.get(device, {}).get('available')]


def select(requested, capabilities):
    requested = requested_device(requested)
    order = candidates(requested, capabilities)
    if not order:
        reasons = '; '.join(f'{d}: {capabilities.get(d, {}).get("reason", "не найден")}'
                            for d in (DEVICES if requested == 'AUTO' else (requested,)))
        raise ValueError('Нет доступного обработчика речи. ' + reasons)
    return order[0]
