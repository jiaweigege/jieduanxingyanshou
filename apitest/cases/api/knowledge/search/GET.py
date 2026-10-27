from app import db
from app.models import KnowledgeChunk


def run(context):
    context.login("student_a", "test-password")
    response = context.client.get("/api/knowledge/search?q=三角形面积公式")
    assert response.status_code == 200
    results = response.get_json()["results"]
    assert results and all(item["material_id"] == context.ids["material_a"] for item in results)
    with context.app.app_context():
        for result in results:
            chunk = KnowledgeChunk.query.filter_by(chunk_id=result["chunk_id"]).one_or_none()
            assert chunk is not None
            assert chunk.class_id == context.ids["class_a"]
            assert result["passage"] in chunk.body
    absent = context.client.get("/api/knowledge/search?q=仅B班可见的独特短语")
    assert absent.status_code == 200
    assert absent.get_json() == {"results": []}
    invalid = context.client.get("/api/knowledge/search?q=%20")
    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "invalid_query"}
