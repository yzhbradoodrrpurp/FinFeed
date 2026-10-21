"""Browser projections leave durable calculation and provider snapshots intact."""


def security_snapshot(value, *, summary=False):
    # Neither field is consumed by the browser. The backend needs both to
    # recalculate metrics and reuse provider observations on subsequent refresh.
    result = {key: item for key, item in value.items()
              if key not in {'series', 'longbridge_market'}}
    if summary:
        result['metrics'] = {key: {field: item for field, item in metric.items()
                                  if field not in {'inputs', 'basis', 'source'}}
                             for key, metric in value.get('metrics', {}).items()}
        result.update(bootstrap=True, partial=True)
    return result
