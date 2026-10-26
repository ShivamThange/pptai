"""Pack atomic judge obligations; admission remains owned by the gateway."""
from infrastructure.llm.context_budget import ContextBudgetError


def generate_atomic_batches(caller, items, request_factory):
    queue = [list(items)]
    while queue:
        batch = queue.pop(0)
        if not batch:
            continue
        kwargs = request_factory(batch)
        if hasattr(caller, 'prepare_structured_request'):
            try:
                prepared = caller.prepare_structured_request(**kwargs)
            except ContextBudgetError as error:
                if error.code == 'REQUIRED_CONTEXT_TOO_LARGE' and len(batch) > 1:
                    middle = len(batch) // 2
                    queue[:0] = [batch[:middle], batch[middle:]]
                    continue
                raise
            yield batch, caller.generate_prepared(prepared)
        else:
            yield batch, caller.generate_structured(**kwargs)


async def generate_atomic_batches_async(caller, items, request_factory):
    queue = [list(items)]
    while queue:
        batch = queue.pop(0)
        if not batch:
            continue
        kwargs = request_factory(batch)
        if hasattr(caller, 'prepare_structured_request'):
            try:
                prepared = caller.prepare_structured_request(**kwargs)
            except ContextBudgetError as error:
                if error.code == 'REQUIRED_CONTEXT_TOO_LARGE' and len(batch) > 1:
                    middle = len(batch) // 2
                    queue[:0] = [batch[:middle], batch[middle:]]
                    continue
                raise
            yield batch, await caller.generate_prepared_async(prepared)
        else:
            yield batch, await caller.generate_structured_async(**kwargs)
