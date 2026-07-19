from datetime import datetime

from app.db.models import FileRecord, User
from app.services import vector_store


class FakeEmbeddingModel:
    def encode(self, texts, normalize_embeddings=True):
        return FakeEmbeddingResult([[0.1, 0.2] for _ in texts])


class FakeEmbeddingResult(list):
    def tolist(self):
        return list(self)


class FakeSearchCollection:
    def __init__(self):
        self.query_kwargs = None

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
            "documents": [["own content"]],
            "metadatas": [[{"user_id": 7, "file_id": "own-file"}]],
            "distances": [[0.1]],
        }


class FakeRebuildCollection:
    def __init__(self, other_user_id):
        self.other_user_id = other_user_id
        self.vectors = [
            {
                "id": "other-vector",
                "metadata": {"user_id": other_user_id, "file_id": "file-b"},
            }
        ]
        self.delete_calls = []
        self.add_calls = []

    def delete(self, where):
        self.delete_calls.append(where)
        user_id = where.get("user_id")
        self.vectors = [
            vector
            for vector in self.vectors
            if vector["metadata"].get("user_id") != user_id
        ]

    def add(self, **kwargs):
        self.add_calls.append(kwargs)
        for vector_id, metadata in zip(kwargs["ids"], kwargs["metadatas"]):
            self.vectors.append({"id": vector_id, "metadata": metadata})


def create_user(db_session, username):
    user = User(
        username=username,
        password_hash="unused-in-vector-test",
        is_active=True,
        is_admin=False,
        created_at=datetime.now().isoformat(timespec="seconds"),
        last_login_at=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def create_file(db_session, user, file_id):
    now = datetime.now().isoformat(timespec="seconds")
    record = FileRecord(
        user_id=user.id,
        file_id=file_id,
        filename=f"{file_id}.txt",
        file_type="txt",
        file_path=f"{file_id}.txt",
        status="uploaded",
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    db_session.add(record)
    db_session.commit()
    return record


def test_vector_search_uses_current_user_filter(monkeypatch):
    collection = FakeSearchCollection()
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(
        vector_store,
        "get_embedding_model",
        lambda: FakeEmbeddingModel(),
    )

    result = vector_store.search_similar_chunks(
        query="test",
        user_id=7,
        top_k=5,
    )

    assert result["chunks"][0]["content"] == "own content"
    assert collection.query_kwargs["where"] == {"user_id": 7}


def test_user_rebuild_does_not_delete_other_users_vectors(
    db_session,
    monkeypatch,
):
    user_a = create_user(db_session, "alice")
    user_b = create_user(db_session, "bob")
    create_file(db_session, user_a, "file-a")
    create_file(db_session, user_b, "file-b")
    collection = FakeRebuildCollection(other_user_id=user_b.id)
    monkeypatch.setattr(vector_store, "get_collection", lambda: collection)
    monkeypatch.setattr(
        vector_store,
        "get_embedding_model",
        lambda: FakeEmbeddingModel(),
    )
    monkeypatch.setattr(
        vector_store,
        "load_document_text",
        lambda file_path, file_type, user_id: "user a content",
    )

    result = vector_store.rebuild_vector_store(db_session, user_a.id)

    assert result["indexed_files"] == 1
    assert collection.delete_calls == [{"user_id": user_a.id}]
    assert any(
        vector["metadata"].get("user_id") == user_b.id
        for vector in collection.vectors
    )
    assert all(
        metadata["user_id"] == user_a.id
        for call in collection.add_calls
        for metadata in call["metadatas"]
    )
