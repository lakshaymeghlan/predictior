[Exchanges / Market APIs] -> [Ingestion Workers] -> [Raw S3] -> [TimescaleDB/Postgres]
                                              \
                                               -> [Feature store (process jobs)]
                                                    |
                                              [Training Workers / Model Store]
                                                    |
                                       [Model Registry (versions) & Metrics DB]
                                                    |
                    +-------------------------------+-------------------------------+
                    |                                                               |
              [Backtester UI]                                                [API Layer (FastAPI)]
              (Next.js frontend)                                              /predict, /backtest, /status
                    |                                                               |
                    +----------------------------[Message Queue: Redis/Celery]-----+
                                                    |
                                          [Live inference workers]
                                                    |
                                          [Paper Trading (CCXT/Alpaca)]
                                                    |
                                              [Monitoring/Alerts (Prometheus/Grafana/Sentry)]
