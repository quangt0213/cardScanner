"""HTTP surface: upload validation, job status, history, health. All heavy work is
delegated to the pipeline via the job service; routes stay thin."""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from utils.image_utils import is_valid_jpeg
from utils.logger import get_logger

log = get_logger("routes.scan")


def build_scan_blueprint(ctx) -> Blueprint:
    bp = Blueprint("scan", __name__)
    cfg = ctx.config

    def _read_upload() -> bytes:
        if "image" in request.files:
            return request.files["image"].read()
        return request.get_data(cache=False)

    @bp.get("/health")
    def health():
        return jsonify({
            "ok": True,
            "service": "raspi-card-scanner",
            "cards": ctx.repository.card_count(),
            "index": len(ctx.pipeline.index),
            "db_bytes": ctx.repository.db_size_bytes(),
            "provider_configured": cfg.provider_configured,
            "ocr_enabled": cfg.ocr_enabled,
        })

    @bp.post("/scan")
    def scan():
        data = _read_upload()
        if not data:
            return jsonify({"error": "empty upload"}), 400
        if len(data) > cfg.max_upload_bytes:
            return jsonify({"error": "upload too large"}), 413
        if not is_valid_jpeg(data):
            return jsonify({"error": "not a JPEG"}), 415

        async_mode = request.args.get("async") == "1" or not cfg.blocking_scan_response
        if async_mode:
            job_id = ctx.jobs.submit(ctx.pipeline.process, data)
            return jsonify({"job_id": job_id, "status": "queued"}), 202

        try:
            result = ctx.jobs.run_blocking(ctx.pipeline.process, data)
        except TimeoutError:
            return jsonify({"error": "scan timed out"}), 504
        return jsonify(result)

    @bp.get("/jobs/<job_id>")
    def job_status(job_id):
        job = ctx.jobs.get(job_id)
        if not job:
            return jsonify({"error": "unknown job"}), 404
        return jsonify(job)

    @bp.get("/history")
    def history():
        limit = min(int(request.args.get("limit", 25)), 200)
        return jsonify({"scans": ctx.repository.recent_scans(limit)})

    return bp
