import asyncio
import logging
import time
from typing import List, Dict, Tuple, Optional, Any

import numpy as np

from database.face import FaceDatabaseManager
from .session_utils import init_face_recognizer_session
from .preprocess import (
    align_faces_batch,
    preprocess_batch,
)
from .postprocess import (
    normalize_embeddings_batch,
    find_best_match,
    find_best_matches_batch,
)

logger = logging.getLogger(__name__)


class FaceRecognizer:
    def __init__(
        self,
        model_path: str,
        input_size: Tuple[int, int],
        similarity_threshold: float,
        providers: Optional[List[str]],
        legacy_database_path: Optional[str],
        session_options: Optional[Dict[str, Any]],
        legacy_source_path: Optional[str] = None,
    ):
        self.model_path = model_path
        self.input_size = input_size
        self.similarity_threshold = similarity_threshold
        self.providers = providers or ["CPUExecutionProvider"]
        self.legacy_database_path = legacy_database_path

        self.INPUT_MEAN = 127.5
        self.INPUT_STD = 127.5

        self.session, self.input_name = init_face_recognizer_session(
            model_path, self.providers, session_options
        )

        if self.legacy_database_path:
            if self.legacy_database_path.endswith(".json"):
                self.legacy_sqlite_path = self.legacy_database_path.replace(
                    ".json", ".db"
                )
            else:
                self.legacy_sqlite_path = self.legacy_database_path

            self.db_manager = FaceDatabaseManager(
                self.legacy_sqlite_path, legacy_source_path=legacy_source_path
            )
        else:
            self.legacy_sqlite_path = None
            self.db_manager = None
            logger.warning("No database path provided, running without persistence")

        self._db_managers: Dict[str, FaceDatabaseManager] = {}
        self._persons_cache: Dict[str, Dict[str, np.ndarray]] = {}
        self._template_bank_cache: Dict[str, Tuple[List[str], Optional[np.ndarray]]] = {}
        self._cache_timestamp: Dict[str, float] = {}
        self._cache_ttl = (
            60.0  # Increased from 1.0 to reduce DB load during recognition
        )
        self._cache_locks: Dict[str, asyncio.Lock] = {}

    async def initialize(self):
        """Initialize the recognizer: migrate legacy data and load cache"""
        if self.db_manager:
            success, message = await self.db_manager.migrate_legacy_data()
            if success:
                logger.info(message)
            await self._refresh_cache()

    def finalize_legacy_migration(self) -> None:
        if not self.db_manager:
            return
        try:
            backup_paths = self.db_manager.finalize_legacy_migration()
            for backup_path in backup_paths:
                logger.info("Archived imported legacy face database at %s", backup_path)
        except OSError as exc:
            logger.warning(
                "Legacy face database was imported but could not be archived; "
                "the source was retained for a safe retry: %s",
                exc,
            )

    @staticmethod
    def _cache_key(organization_id: Optional[str]) -> str:
        return organization_id or "__global__"

    def _get_db_manager(
        self, organization_id: Optional[str] = None
    ) -> Optional[FaceDatabaseManager]:
        if self.legacy_sqlite_path is None:
            return None

        if organization_id is None:
            return self.db_manager

        cache_key = self._cache_key(organization_id)
        manager = self._db_managers.get(cache_key)
        if manager is None:
            manager = FaceDatabaseManager(organization_id=organization_id)
            self._db_managers[cache_key] = manager
        return manager

    async def _extract_embeddings(
        self, image: np.ndarray, face_data_list: List[Dict]
    ) -> List[np.ndarray]:
        """
        Extract embeddings for faces using batch processing.

        Args:
            image: Input image (BGR format)
            face_data_list: List of face data dicts with 'landmarks_5' key

        Returns:
            List of normalized embeddings
        """
        if not face_data_list:
            return []

        aligned_faces = align_faces_batch(image, face_data_list, self.input_size)

        if not aligned_faces:
            return []

        batch_input = preprocess_batch(aligned_faces, self.INPUT_MEAN, self.INPUT_STD)

        feeds = {self.input_name: batch_input}

        # Offload blocking ONNX inference to a background thread
        loop = asyncio.get_running_loop()
        outputs = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: self.session.run(None, feeds)),
            timeout=10.0,
        )
        embeddings = outputs[0]

        return normalize_embeddings_batch(embeddings)

    def _template_bank_store(
        self,
    ) -> Dict[str, Tuple[List[str], Optional[np.ndarray]]]:
        store = getattr(self, "_template_bank_cache", None)
        if store is None:
            store = {}
            self._template_bank_cache = store
        return store

    async def _load_template_bank(
        self, db_manager: Optional[FaceDatabaseManager]
    ) -> Tuple[List[str], Optional[np.ndarray]]:
        if not db_manager:
            return [], None
        person_ids, vectors = await db_manager.get_all_template_entries()
        if not vectors:
            return [], None
        expected_dim = len(vectors[0])
        filtered_ids: List[str] = []
        filtered_vecs: List[np.ndarray] = []
        for pid, vec in zip(person_ids, vectors):
            if len(vec) == expected_dim:
                filtered_ids.append(pid)
                filtered_vecs.append(vec)
        if not filtered_vecs:
            return [], None
        return filtered_ids, np.stack(filtered_vecs)

    async def _get_database(
        self, organization_id: Optional[str] = None
    ) -> Dict[str, np.ndarray]:
        """
        Get person database with caching.

        Returns:
            Dictionary mapping person_id to embedding
        """
        cache_key = self._cache_key(organization_id)
        if cache_key not in self._cache_locks:
            self._cache_locks[cache_key] = asyncio.Lock()

        bank_store = self._template_bank_store()
        async with self._cache_locks[cache_key]:
            current_time = time.time()
            cache_timestamp = self._cache_timestamp.get(cache_key, 0)
            if (
                cache_key not in self._persons_cache
                or (current_time - cache_timestamp) > self._cache_ttl
            ):
                db_manager = self._get_db_manager(organization_id)
                if db_manager:
                    self._persons_cache[cache_key] = await db_manager.get_all_persons()
                    bank_store[cache_key] = await self._load_template_bank(db_manager)
                else:
                    self._persons_cache[cache_key] = {}
                    bank_store[cache_key] = ([], None)
                self._cache_timestamp[cache_key] = current_time

            return self._persons_cache[cache_key]

    async def export_template_bank(
        self, organization_id: Optional[str] = None
    ) -> Tuple[List[str], Optional[np.ndarray]]:
        """Return multi-angle template matrix and aligned person_id list for org scope."""
        await self._get_database(organization_id)
        cache_key = self._cache_key(organization_id)
        return self._template_bank_store().get(cache_key, ([], None))

    async def _find_best_match(
        self,
        embedding: np.ndarray,
        allowed_person_ids: Optional[List[str]] = None,
        organization_id: Optional[str] = None,
        prebuilt_matrix: Optional[np.ndarray] = None,
        person_index_map: Optional[List[str]] = None,
    ) -> Tuple[Optional[str], float]:
        """
        Find best matching person using cached database.

        Uses Postprocessing Layer for similarity matching.
        """
        if not self._get_db_manager(organization_id):
            return None, 0.0

        database = await self._get_database(organization_id)

        if not database and prebuilt_matrix is None:
            return None, 0.0

        if prebuilt_matrix is None:
            bank_ids, bank_matrix = await self.export_template_bank(organization_id)
            if bank_matrix is not None and bank_ids:
                prebuilt_matrix = bank_matrix
                person_index_map = bank_ids

        return find_best_match(
            embedding,
            database,
            self.similarity_threshold,
            allowed_person_ids,
            prebuilt_matrix=prebuilt_matrix,
            person_index_map=person_index_map,
        )

    async def _refresh_cache(self, organization_id: Optional[str] = None):
        """Refresh cache after database modifications"""
        cache_key = self._cache_key(organization_id)
        if cache_key not in self._cache_locks:
            self._cache_locks[cache_key] = asyncio.Lock()
        bank_store = self._template_bank_store()
        # An older cache load must finish before publishing the post-write state.
        async with self._cache_locks[cache_key]:
            db_manager = self._get_db_manager(organization_id)
            if db_manager:
                self._persons_cache[cache_key] = await db_manager.get_all_persons()
                bank_store[cache_key] = await self._load_template_bank(db_manager)
                self._cache_timestamp[cache_key] = time.time()
            else:
                self._persons_cache.pop(cache_key, None)
                bank_store.pop(cache_key, None)
                self._cache_timestamp.pop(cache_key, None)

        try:
            from services.live_stream_service import LiveStreamService

            LiveStreamService.invalidate_all(organization_id)
        except Exception as inv_err:
            logger.debug("Failed to invalidate live stream service cache: %s", inv_err)

    async def export_embeddings(
        self, organization_id: Optional[str] = None
    ) -> Dict[str, np.ndarray]:
        """Return decrypted embeddings for the requested org scope."""
        return await self._get_database(organization_id)

    async def refresh_cache(self, organization_id: Optional[str] = None):
        await self._refresh_cache(organization_id)

    async def recognize_face(
        self,
        image: np.ndarray,
        landmarks_5: List,
        allowed_person_ids: Optional[List[str]] = None,
        organization_id: Optional[str] = None,
    ) -> Dict:
        try:
            face_data = [{"landmarks_5": landmarks_5}]
            embeddings = await self._extract_embeddings(image, face_data)

            if not embeddings:
                return {
                    "person_id": None,
                    "similarity": 0.0,
                    "success": False,
                    "error": "Failed to extract embedding",
                }

            embedding = embeddings[0]
            person_id, similarity = await self._find_best_match(
                embedding, allowed_person_ids, organization_id
            )

            result = {
                "person_id": person_id,
                "similarity": similarity,
                "success": person_id is not None,
            }

            return result

        except Exception as e:
            logger.error(f"Face recognition error: {e}")
            return {
                "person_id": None,
                "similarity": 0.0,
                "success": False,
                "error": str(e),
            }

    async def recognize_faces(
        self,
        image: np.ndarray,
        faces: List[Dict],
        allowed_person_ids: Optional[List[str]] = None,
        organization_id: Optional[str] = None,
        prebuilt_matrix: Optional[np.ndarray] = None,
        person_index_map: Optional[List[str]] = None,
    ) -> List[Dict]:
        try:
            if not faces:
                return []

            embeddings = await self._extract_embeddings(image, faces)
            if len(embeddings) != len(faces):
                raise ValueError("Failed to extract embeddings for all faces")

            database = await self._get_database(organization_id)
            if prebuilt_matrix is None:
                bank_ids, bank_matrix = await self.export_template_bank(
                    organization_id
                )
                if bank_matrix is not None and bank_ids:
                    prebuilt_matrix = bank_matrix
                    person_index_map = bank_ids
            matches = find_best_matches_batch(
                query_embeddings=embeddings,
                database=database,
                similarity_threshold=self.similarity_threshold,
                allowed_person_ids=allowed_person_ids,
                prebuilt_matrix=prebuilt_matrix,
                person_index_map=person_index_map,
            )

            results: List[Dict] = [
                {
                    "person_id": person_id,
                    "similarity": similarity,
                    "success": person_id is not None,
                }
                for person_id, similarity in matches
            ]
            return results
        except Exception as e:
            logger.error(f"Face batch recognition error: {e}")
            return [
                {
                    "person_id": None,
                    "similarity": 0.0,
                    "success": False,
                    "error": str(e),
                }
                for _ in faces
            ]

    async def enroll_person(
        self,
        person_id: str,
        image: np.ndarray,
        landmarks_5: List,
        organization_id: Optional[str] = None,
    ) -> Dict:
        try:
            face_data = [{"landmarks_5": landmarks_5}]
            embeddings = await self._extract_embeddings(image, face_data)

            if not embeddings:
                return {
                    "success": False,
                    "error": "Failed to extract embedding",
                    "person_id": person_id,
                }

            embedding = embeddings[0]

            db_manager = self._get_db_manager(organization_id)
            if not db_manager:
                return {
                    "success": False,
                    "person_id": person_id,
                    "database_saved": False,
                    "error": "Face storage is unavailable. Please restart Facenox and try again.",
                }

            from utils.image_utils import calculate_image_hash

            image_hash = calculate_image_hash(image)
            save_success = await db_manager.add_person(person_id, embedding, image_hash)
            if not save_success:
                return {
                    "success": False,
                    "person_id": person_id,
                    "database_saved": False,
                    "error": "Failed to save face data. Please try enrolling again.",
                }

            stats = await db_manager.get_stats()
            total_persons = stats.get("total_persons", 0)
            await self._refresh_cache(organization_id)

            return {
                "success": True,
                "person_id": person_id,
                "database_saved": True,
                "total_persons": total_persons,
            }

        except Exception as e:
            logger.error(f"Person enrollment failed: {e}")
            return {"success": False, "error": str(e), "person_id": person_id}

    async def enroll_person_multi_angle(
        self,
        person_id: str,
        samples: List[Dict[str, Any]],
        organization_id: Optional[str] = None,
        min_consistency_similarity: float = 0.25,
    ) -> Dict[str, Any]:
        """Extract 512-d embeddings for >=5 angles, verify identity consistency, fuse & persist encrypted."""
        try:
            if len(samples) < 5:
                return {
                    "success": False,
                    "person_id": person_id,
                    "error": f"At least 5 distinct face angle captures are required (got {len(samples)}).",
                }

            db_manager = self._get_db_manager(organization_id)
            if not db_manager:
                return {
                    "success": False,
                    "person_id": person_id,
                    "database_saved": False,
                    "error": "Face storage is unavailable. Please restart Facenox and try again.",
                }

            extracted_vectors: List[np.ndarray] = []
            template_records: List[Dict[str, Any]] = []
            weights: List[float] = []
            front_vec: Optional[np.ndarray] = None

            for sample in samples:
                face_data = [{"landmarks_5": sample["landmarks_5"]}]
                embeddings = await self._extract_embeddings(sample["image"], face_data)
                if not embeddings:
                    return {
                        "success": False,
                        "person_id": person_id,
                        "error": f"Failed to extract facial features for angle '{sample['angle']}'.",
                    }
                vec = embeddings[0].astype(np.float32)
                norm = float(np.linalg.norm(vec))
                if norm > 0:
                    vec = vec / norm

                angle = str(sample["angle"])
                clarity = float(sample.get("clarity_score", 0.5))
                if angle == "front":
                    front_vec = vec
                    weight = max(0.45, clarity) * 1.25
                elif angle in ("slight_left", "slight_right"):
                    weight = max(0.35, clarity) * 1.0
                else:
                    weight = max(0.30, clarity) * 0.85

                extracted_vectors.append(vec)
                weights.append(weight)
                template_records.append(
                    {
                        "angle": angle,
                        "embedding": vec,
                        "yaw": float(sample.get("yaw", 0.0)),
                        "pitch": float(sample.get("pitch", 0.0)),
                        "clarity_score": clarity,
                    }
                )

            # Pairwise / centroid consistency check so someone cannot mix two people across 5 shots
            stacked = np.stack(extracted_vectors)
            weight_arr = np.asarray(weights, dtype=np.float32)[:, None]
            fused = np.sum(stacked * weight_arr, axis=0)
            fused_norm = float(np.linalg.norm(fused))
            if fused_norm <= 0:
                return {
                    "success": False,
                    "person_id": person_id,
                    "error": "Invalid facial template norm computed during fusion.",
                }
            fused = (fused / fused_norm).astype(np.float32)

            ref_vec = front_vec if front_vec is not None else fused
            for idx, vec in enumerate(extracted_vectors):
                sim_centroid = float(np.dot(vec, fused))
                sim_ref = float(np.dot(vec, ref_vec))
                if sim_centroid < min_consistency_similarity and sim_ref < min_consistency_similarity:
                    return {
                        "success": False,
                        "person_id": person_id,
                        "error": (
                            f"Captured image for '{template_records[idx]['angle']}' does not match "
                            "the same person as the other captures. Please recapture clearly."
                        ),
                    }

            from utils.image_utils import calculate_image_hash

            primary_img = next(
                (s["image"] for s in samples if s["angle"] == "front"),
                samples[0]["image"],
            )
            image_hash = calculate_image_hash(primary_img)

            save_fused = await db_manager.add_person(person_id, fused, image_hash)
            save_angles = await db_manager.save_angle_templates(
                person_id, template_records
            )
            if not save_fused or not save_angles:
                return {
                    "success": False,
                    "person_id": person_id,
                    "database_saved": False,
                    "error": "Failed to persist encrypted multi-angle face templates.",
                }

            stats = await db_manager.get_stats()
            total_persons = stats.get("total_persons", 0)
            await self._refresh_cache(organization_id)

            return {
                "success": True,
                "person_id": person_id,
                "database_saved": True,
                "angles_enrolled": [r["angle"] for r in template_records],
                "angle_count": len(template_records),
                "total_persons": total_persons,
            }
        except Exception as e:
            logger.error(f"Multi-angle person enrollment failed: {e}")
            return {"success": False, "error": str(e), "person_id": person_id}

    async def remove_person(
        self, person_id: str, organization_id: Optional[str] = None
    ) -> Dict:
        """Remove a person from the database"""
        try:
            db_manager = self._get_db_manager(organization_id)
            if db_manager:
                remove_success = await db_manager.remove_person(person_id)

                if remove_success:
                    await self._refresh_cache(organization_id)
                    stats = await db_manager.get_stats()
                    total_persons = stats.get("total_persons", 0)

                    return {
                        "success": True,
                        "person_id": person_id,
                        "database_saved": True,
                        "total_persons": total_persons,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Person {person_id} not found in database",
                        "person_id": person_id,
                    }
            else:
                return {
                    "success": False,
                    "error": "No database manager available",
                    "person_id": person_id,
                }

        except Exception as e:
            logger.error(f"Person removal failed: {e}")
            return {"success": False, "error": str(e), "person_id": person_id}

    async def get_all_persons(self, organization_id: Optional[str] = None) -> List[str]:
        """Get list of all enrolled person IDs using the high-performance cache."""
        database = await self._get_database(organization_id)
        return list(database.keys())

    async def update_person_id(
        self,
        old_person_id: str,
        new_person_id: str,
        organization_id: Optional[str] = None,
    ) -> Dict:
        """Update a person's ID in the database"""
        try:
            db_manager = self._get_db_manager(organization_id)
            if db_manager:
                updated_count = await db_manager.update_person_id(
                    old_person_id, new_person_id
                )
                if updated_count > 0:
                    await self._refresh_cache(organization_id)
                    return {
                        "success": True,
                        "message": f"Person '{old_person_id}' renamed to '{new_person_id}' successfully",
                        "updated_records": updated_count,
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Person '{old_person_id}' not found or '{new_person_id}' already exists",
                        "updated_records": 0,
                    }
            else:
                return {
                    "success": False,
                    "error": "No database manager available",
                    "updated_records": 0,
                }

        except Exception as e:
            logger.error(f"Person update failed: {e}")
            return {"success": False, "error": str(e), "updated_records": 0}

    async def get_stats(self, organization_id: Optional[str] = None) -> Dict:
        """Get face recognition statistics"""
        total_persons = 0
        persons = []

        db_manager = self._get_db_manager(organization_id)
        if db_manager:
            stats = await db_manager.get_stats()
            total_persons = stats.get("total_persons", 0)
            persons = await db_manager.get_all_persons_with_details()

        return {"total_persons": total_persons, "persons": persons}

    def set_similarity_threshold(self, threshold: float):
        """Update similarity threshold for recognition"""
        self.similarity_threshold = threshold

    async def clear_database(self, organization_id: Optional[str] = None) -> Dict:
        """Clear all persons from the database"""
        try:
            db_manager = self._get_db_manager(organization_id)
            if db_manager:
                clear_success = await db_manager.clear_database()

                if clear_success:
                    await self._refresh_cache(organization_id)
                    return {"success": True, "database_saved": True, "total_persons": 0}
                else:
                    return {"success": False, "error": "Failed to clear database"}
            else:
                return {"success": False, "error": "No database manager available"}

        except Exception as e:
            logger.error(f"Database clearing failed: {e}")
            return {"success": False, "error": str(e)}

    def _invalidate_cache(self, organization_id: Optional[str] = None):
        """Invalidate cache without refreshing"""
        if organization_id is None:
            self._persons_cache.clear()
            self._cache_timestamp.clear()
            return

        cache_key = self._cache_key(organization_id)
        self._persons_cache.pop(cache_key, None)
        self._cache_timestamp.pop(cache_key, None)

    def invalidate_cache(self, organization_id: Optional[str] = None):
        self._invalidate_cache(organization_id)
