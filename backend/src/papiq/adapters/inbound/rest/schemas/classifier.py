"""The classifier's status."""

from datetime import datetime

from pydantic import BaseModel, Field

from papiq.core.domain.classifier import ClassifierModel
from papiq.core.services.classifier import ClassifierStatus


class ClassesOut(BaseModel):
    contact: int = Field(default=0, description="Contacts it can name.")
    document_type: int = Field(default=0, description="Document types it can name.")
    tags: int = Field(default=0, description="Tags it can name.")


class AccuracyOut(BaseModel):
    tested: int = Field(description="Examples held out (a fifth) to measure the model.")
    contact: float | None = Field(description="Share of them whose contact it named first.")
    document_type: float | None = Field(description="Share whose type it named first.")


class ClassifierModelOut(BaseModel):
    number: int = Field(description="Counts the trainings: the first model is 1.")
    trained_at: datetime
    examples: int = Field(description="Confirmed documents it learned from.")
    examples_until: datetime | None = Field(
        description="When the latest of them was confirmed; later confirmations count "
        "towards the next training."
    )
    classes: ClassesOut
    learned_identifiers: int = Field(
        description="Identifiers of contacts training learned from the same documents."
    )
    accuracy: AccuracyOut | None = Field(
        description="Measured from 50 examples on: trained on four fifths, tested on the rest."
    )
    method: str | None = Field(examples=["scikit-learn 1.9.1 papiq-tfidf-logreg/1"])

    @classmethod
    def of(cls, model: ClassifierModel) -> "ClassifierModelOut":
        summary = model.summary
        classes = summary.get("classes")
        accuracy = summary.get("accuracy")
        learned = summary.get("learned_identifiers")
        method = summary.get("method")
        return cls(
            number=model.number,
            trained_at=model.trained_at,
            examples=model.examples,
            examples_until=model.examples_until,
            classes=ClassesOut.model_validate(classes if isinstance(classes, dict) else {}),
            learned_identifiers=learned if isinstance(learned, int) else 0,
            accuracy=(AccuracyOut.model_validate(accuracy) if isinstance(accuracy, dict) else None),
            method=method if isinstance(method, str) else None,
        )


class ClassifierStatusOut(BaseModel):
    model: ClassifierModelOut | None = Field(description="The latest model; null before any.")
    confirmed: int = Field(description="Documents a person confirmed (the training examples).")
    since: int = Field(description="Of them, confirmed after the latest model's examples.")
    min_examples: int = Field(description="Confirmed documents the first model needs.")
    retrain_after: int = Field(description="Confirmations after which it is trained again.")
    threshold: float = Field(description="How sure a prediction must be to name its class.")

    @classmethod
    def of(cls, status: ClassifierStatus) -> "ClassifierStatusOut":
        return cls(
            model=None if status.model is None else ClassifierModelOut.of(status.model),
            confirmed=status.confirmed,
            since=status.since,
            min_examples=status.policy.min_examples,
            retrain_after=status.policy.retrain_after,
            threshold=status.policy.threshold,
        )
