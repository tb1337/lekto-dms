"""`python -m papiq.composition train`: train the classifier from the confirmed documents, in
the foreground, and learn identifiers of contacts from them. The same training the worker runs
as a job (after enough confirmations, or `POST /classifier/train`); do not run both at once."""

from papiq.composition.container import build_container, build_services
from papiq.composition.errors import ConfigurationError
from papiq.composition.settings import Settings
from papiq.core.domain.classifier import ClassifierModel


async def run_training(settings: Settings) -> ClassifierModel:
    if settings.classifier == "none":
        raise ConfigurationError("PAPIQ_CLASSIFIER is none: there is no classifier to train")
    container = build_container(settings)
    try:
        services = build_services(container, settings)
        assert services.classifier is not None
        return await services.classifier.train()
    finally:
        await container.aclose()
