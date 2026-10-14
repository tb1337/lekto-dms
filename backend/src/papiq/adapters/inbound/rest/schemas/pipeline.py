"""The processing graph."""

from pydantic import BaseModel, ConfigDict, Field

from papiq.core.domain.pipeline import Node


class GraphNodeOut(BaseModel):
    node: Node
    requires: list[Node] = Field(description="The nodes whose results this node needs.")


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
                    ]
                }
            ]
        }
    )

    nodes: list[GraphNodeOut] = Field(description="In graph order: every node after its needs.")


class ReparseOut(BaseModel):
    queued: int = Field(
        description="Documents whose text is read again (not those queued already)."
    )
