import os


def get_path(code):
    target_suffix = f"_{code}"
    matches = sorted(
        log for log in os.listdir("logs")
        if log.endswith(target_suffix)
    )
    if not matches:
        raise FileNotFoundError(
            f"No log directory under logs/ matches code={code!r}"
        )
    return f"logs/{matches[-1]}"
