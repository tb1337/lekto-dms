"""The processing graph."""

from pydantic import BaseModel, ConfigDict, Field

from lekto.core.domain.pipeline import Node


class GraphNodeOut(BaseModel):
    node: Node
    requires: list[Node] = Field(description="The nodes whose results this node needs.")
    waits_for: list[Node] = Field(
        default=[],
        description=(
            "Nodes this node also waits for without needing their results; processing again "
            "from one of them leaves this node alone."
        ),
    )


class VisionOut(BaseModel):
    model: str
    endpoint: str = Field(description="Where the page images go: host and port.")


class PipelineOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "nodes": [
                        {"node": "receive", "requires": []},
                        {"node": "ocr", "requires": ["receive"]},
                        {"node": "pages", "requires": ["receive"]},
                        {"node": "parse", "requires": ["ocr"]},
                        {"node": "file", "requires": ["apply_rules", "pages"]},
                    ],
                    "vision": {"model": "claude-sonnet-5-5", "endpoint": "chat.example"},
                    "logo_fetch": False,
                    "meaning_search": True,
                }
            ]
        }
    )

    nodes: list[GraphNodeOut] = Field(description="In graph order: every node after its needs.")
    vision: VisionOut | None = Field(
        description=(
            "The vision language model a person can have documents read with (`POST "
            "/documents/{id}/vision`); none if it is not configured."
        )
    )
    logo_fetch: bool = Field(
        description=(
            "Whether Lekto fetches the logos of contacts from their websites "
            "(`LEKTO_LOGO_FETCH`; `POST /contacts/{id}/logo/fetch`)."
        )
    )
    meaning_search: bool = Field(
        description=(
            "Whether the search takes the meaning into account besides the words (a search "
            "index and embeddings are set up): only then does a client say how a search "
            "searched (`mode`, `reason`) and warm the model (`POST /documents/search/warm`)."
        )
    )


class ReparseOut(BaseModel):
    queued: int = Field(
        description="Documents whose text is read again (not those queued already)."
    )


class QueuedOut(BaseModel):
    queued: int = Field(description="How many were queued now (not those queued already).")
