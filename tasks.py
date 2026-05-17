from celery import Celery

celery = Celery(
    'tasks',
    broker='redis://localhost:6379/0'
)

@celery.task
def analyze_data(file_path):
    import pandas as pd

    df = pd.read_csv(file_path)

    result = {
        "rows": len(df),
        "columns": len(df.columns),
    }

    return result