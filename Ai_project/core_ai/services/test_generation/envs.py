from datetime import datetime, timedelta

from django.conf import settings
from pymongo.errors import DuplicateKeyError
import copy


class InMemoryEnvRepo:
    def __init__(self):
        self.items = {}

    def get(self, key):
        return copy.deepcopy(self.items.get(key))

    def claim(self, key, owner, previous=None):
        if self.get(key) != previous:
            return False
        now = datetime.utcnow()
        self.items[key] = dict(env_key=key, owner=owner, status="building", updated_at=now, last_used_at=now)
        return True

    def finish(self, key, owner, **fields):
        item = self.items[key]
        if item["status"] != "building" or item["owner"] != owner:
            return False
        item.update(fields, updated_at=datetime.utcnow())
        return True

    def touch(self, key):
        self.items[key]["last_used_at"] = datetime.utcnow()
        return True


class EnvRepo:
    def __init__(self, collection):
        self.collection = collection
        collection.create_index("env_key", unique=True)

    def get(self, key):
        return self.collection.find_one({"env_key": key}, {"_id": 0})

    def claim(self, key, owner, previous=None):
        now = datetime.utcnow()
        fields = dict(env_key=key, owner=owner, status="building", updated_at=now, last_used_at=now)
        if previous:
            return self.collection.update_one(
                {"env_key": key, "status": previous["status"], "updated_at": previous["updated_at"]},
                {"$set": fields}).matched_count == 1
        try:
            self.collection.insert_one(fields)
            return True
        except DuplicateKeyError:
            return False

    def finish(self, key, owner, **fields):
        return self.collection.update_one({"env_key": key, "owner": owner, "status": "building"},
                                          {"$set": dict(fields, updated_at=datetime.utcnow())}).matched_count == 1

    def touch(self, key):
        return self.collection.update_one({"env_key": key, "status": "ready"},
            {"$set": {"last_used_at": datetime.utcnow()}}).matched_count == 1

    def reap(self, executor, keep_days, lock):
        if not lock.set("testgen:env_reaper", 1, nx=True, ex=3600):
            return
        for doc in self.collection.find({"last_used_at": {"$lt": datetime.utcnow() - timedelta(days=keep_days)},
                                         "status": {"$ne": "building"}}):
            match = {"_id": doc["_id"], "last_used_at": doc["last_used_at"], "status": doc["status"]}
            if not self.collection.update_one(match, {"$set": {"status": "reaping"}}).matched_count:
                continue
            if doc.get("volume"):
                try:
                    executor.remove_volume(doc["volume"])
                except Exception:
                    self.collection.update_one({"_id": doc["_id"], "status": "reaping"},
                                               {"$set": {"status": doc["status"]}})
                    continue
            self.collection.delete_one({"_id": doc["_id"], "status": "reaping"})


def get_env_repo():
    from core_ai.mongo_utils import get_mongo_db
    return EnvRepo(get_mongo_db()[settings.TEST_ENVS_COLLECTION])
