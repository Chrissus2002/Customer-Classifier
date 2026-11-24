import streamlit as st
import pandas as pd
import sys
import os
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from auth import setup_page
from database import (
    get_all_contacts_by_tenant,
    get_latest_daemon_task_run,
    contacts_import_completed,
    initial_login_complete,
    get_active_job,
    get_sync_progress_stats,
    get_import_jobs_by_tenant,
    update_import_job,
    create_import_job,
    get_active_classifier_config,
    get_draft_classifier_config,
    save_classifier_draft,
    activate_classifier_config,
    get_classifier_version_history,
    get_stale_contact_count,
    get_classify_since_date,
    set_classify_since_date,
)

root_project = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_project / "scripts"))

from batch_contact_imports import run_contact_imports

try:
    from streamlit_autorefresh import st_autorefresh
    _HAS_AUTOREFRESH = True
except ImportError:
    _HAS_AUTOREFRESH = False


def _start_backfill(tenant_id: int, job_id: str, limit: int | None = None):
    """Launch batch_messages_import.py as a detached subprocess."""
    log_dir = Path.home() / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / f"backfill-{tenant_id}-{job_id}.log"

    cmd = [
        sys.executable,
        str(root_project / "scripts" / "batch_messages_import.py"),
        "--tenant-id", str(tenant_id),
        "--job-id", job_id,
    ]
    if limit:
        cmd += ["--limit", str(limit)]

    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            cmd,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    update_import_job(job_id, status="running", log_path=str(log_path))
    return proc.pid, str(log_path)


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _write_cancel_flag(job_id: str):
    Path(f"/tmp/dialo-cancel-{job_id}").touch()


# ─── Auth & first-login gate ────────────────────────────────────────────────
setup_page("Admin")

tenant_id = st.session_state["tenant_id"]

if st.session_state.get("first_login") and not st.session_state.get("batch_imports_contacts_done"):
    st.warning("**First time setup:** Please run the contact import before continuing.")
    if st.button("Run initial contact import"):
        with st.spinner("Importing contacts...", show_time=True):
            run_contact_imports(tenant_id)
            contacts_import_completed(tenant_id)
            initial_login_complete(tenant_id)
        st.session_state["contact_import_notice"] = "Contact import completed. Drift updates on the daemon's next run."
        st.session_state["batch_imports_contacts_done"] = True
        st.session_state["first_login"] = False
        st.rerun()
    st.stop()

contacts = get_all_contacts_by_tenant(tenant_id)

# ─── Tabs ───────────────────────────────────────────────────────────────────
tab_ops, tab_classifier = st.tabs(["Operations", "Classifier Configuration"])

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1: Operations
# ═══════════════════════════════════════════════════════════════════════════
with tab_ops:
    drift_run, drift_ok = get_latest_daemon_task_run(tenant_id, "exact_contact_drift")

    notice = st.session_state.pop("contact_import_notice", None)
    if notice:
        st.info(notice)

    if drift_ok and drift_run and drift_run.get("status") == "success":
        dr = drift_run.get("result") or {}
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Wati distinct", f"{dr.get('wati_distinct_contact_count', 0):,}")
        with c2:
            st.metric("DB", f"{dr.get('db_contact_count', 0):,}")
        with c3:
            st.metric("Wati-only", f"{dr.get('wati_only_count', 0):,}")
        with c4:
            st.metric("DB-only", f"{dr.get('db_only_count', 0):,}")

        if dr.get("exact_match", False):
            st.caption("Exact daemon identity match: Wati and DB contact sets are aligned 1:1.")
        else:
            st.warning(
                "Exact daemon identity mismatch: "
                f"{dr.get('wati_only_count', 0)} on Wati only, "
                f"{dr.get('db_only_count', 0)} in DB only."
            )
    elif drift_ok and drift_run and drift_run.get("status") == "running":
        st.info("Exact contact drift is currently being computed by the daemon.")
    elif drift_ok and drift_run:
        message = drift_run.get("error_message") or drift_run.get("notes") or "Unknown error"
        st.warning(f"Latest exact drift run failed: {message}")
    elif drift_ok:
        st.info("Exact contact drift has not been computed yet. The daemon will populate this section on its next run.")
    else:
        st.warning(f"Could not load exact drift status: {drift_run}")

    st.divider()

    # Contact Import
    st.subheader("Contact Import")
    st.caption(
        "Re-import contacts from Wati. Takes a couple of minutes — "
        "the page will be blocked while it runs."
    )
    if st.button("Run contact import", type="primary"):
        with st.spinner("Importing contacts...", show_time=True):
            run_contact_imports(tenant_id)
            contacts_import_completed(tenant_id)
        st.session_state["contact_import_notice"] = "Contact import completed. Drift updates on the daemon's next run."
        st.rerun()

    st.divider()

    # Message Backfill
    st.subheader("Message Backfill")
    st.caption(
        "Import historical messages per contact from Wati. "
        "Runs in the background — you can close this page and come back. "
        "Can take several hours for large tenants."
    )

    active_job, _ = get_active_job(tenant_id)
    if active_job and _HAS_AUTOREFRESH:
        st_autorefresh(interval=5000, key="backfill_autorefresh")

    stats = get_sync_progress_stats(tenant_id)
    total_contacts = len(contacts)
    synced = stats["total_synced"]
    pct = round((synced / total_contacts * 100), 1) if total_contacts > 0 else 0.0

    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Contacts synced", synced)
        with col2:
            st.metric("Total contacts", total_contacts)
        with col3:
            st.metric("% complete", f"{pct}%")

    if active_job:
        job_id = active_job["job_id"]
        pid = active_job.get("subprocess_pid")

        created_raw = active_job.get("created_at", "")
        starting_up = False
        if not pid and created_raw:
            try:
                created_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                starting_up = (datetime.now(timezone.utc) - created_at) < timedelta(seconds=30)
            except Exception:
                pass

        alive = _is_process_alive(pid) if pid else starting_up

        with st.container(border=True):
            st.markdown("**Active Job**")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Status:** {active_job['status']}")
                st.markdown(f"**Started:** {active_job.get('created_at', 'unknown')}")
            with col2:
                st.markdown(f"**Contacts processed:** {active_job.get('processed_messages', 0)}")
                liveness = "Running" if alive else "Process may have exited"
                st.markdown(f"**Process:** {liveness} (PID {pid})")

            if alive:
                if st.button("Stop backfill", type="secondary"):
                    _write_cancel_flag(job_id)
                    st.info("Stop signal sent. The job will finish its current contact, process messages to silver, then exit.")
            else:
                st.warning("Process is no longer running. The job is stuck in 'running' state.")
                if st.button("Force mark as failed", type="secondary"):
                    update_import_job(job_id, status="failed", error_message="Force-failed from UI: process no longer alive")
                    st.rerun()

        log_path = active_job.get("log_path")
        if log_path:
            with st.expander("View log tail"):
                try:
                    log_text = Path(log_path).read_text()
                    st.code(log_text[-8000:] if len(log_text) > 8000 else log_text)
                except Exception as e:
                    st.warning(f"Could not read log: {e}")

    else:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Start message backfill", type="primary"):
                job, ok = create_import_job(tenant_id)
                if not ok:
                    st.error(f"Could not create job: {job}")
                else:
                    pid, log_path = _start_backfill(tenant_id, job["job_id"])
                    st.success(f"Backfill started (PID {pid}). This page will refresh automatically.")
                    st.rerun()
        with col2:
            if st.button("Test run (5 contacts)"):
                job, ok = create_import_job(tenant_id)
                if not ok:
                    st.error(f"Could not create job: {job}")
                else:
                    pid, log_path = _start_backfill(tenant_id, job["job_id"], limit=5)
                    st.success(f"Test run started (PID {pid}, limit=5).")
                    st.rerun()

    st.divider()

    # Job History
    st.subheader("Job History")
    jobs, _ = get_import_jobs_by_tenant(tenant_id, limit=10)
    if jobs:
        history_df = pd.DataFrame([
            {
                "Status": j["status"],
                "Processed": j.get("processed_messages", 0),
                "Started": (j.get("created_at") or "")[:16].replace("T", " "),
                "Completed": (j.get("completed_at") or "")[:16].replace("T", " "),
                "Job ID": j["job_id"][:8],
            }
            for j in jobs
        ])
        st.dataframe(history_df, use_container_width=True, hide_index=True)
    else:
        st.info("No import jobs have been run yet.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2: Classifier Configuration
# ═══════════════════════════════════════════════════════════════════════════
with tab_classifier:
    active_config, retrieved_active = get_active_classifier_config(tenant_id)
    if not retrieved_active:
        st.error("Could not retrieve active config")
        st.stop()
    draft_config, retrieved_draft = get_draft_classifier_config(tenant_id)
    if not retrieved_draft:
        st.error("Could not retrieve draft config")
        st.stop()

    # Active version banner
    if active_config:
        stale_count = get_stale_contact_count(tenant_id, active_config["version"])
        banner_cols = st.columns([3, 1])
        with banner_cols[0]:
            activated_str = active_config.get("activated_at") or active_config.get("created_at") or "—"
            st.info(f"**Active: v{active_config['version']}** — activated {activated_str[:10]}, {len(active_config.get('stages', []))} stages")
        with banner_cols[1]:
            if stale_count > 0:
                est_cost = round(stale_count * 0.0003, 2)
                st.warning(f"{stale_count} contacts stale (~${est_cost})")
    else:
        st.warning("No active classifier config found. Run `python scripts/seed_classifier_configs.py` first.")

    # Stale contacts reclassification
    if active_config and stale_count > 0:
        with st.container(border=True):
            st.markdown(f"**{stale_count} contacts classified with older version. Active is v{active_config['version']}.**")
            est_cost = round(stale_count * 0.0003, 2)
            if st.button(f"Reclassify stale contacts (~${est_cost})", key="reclassify_btn"):
                try:
                    from classifiers.factory import get_classifier
                    from classifiers.orchestrator import JourneyClassifier
                    provider = get_classifier()
                    orchestrator = JourneyClassifier(classifier=provider)
                    tenant_cfg = orchestrator.get_tenant_config(tenant_id)
                    since_date = get_classify_since_date(tenant_id) or "2026-01-01"
                    stale_candidates, _ = orchestrator.get_unclassified_contacts(tenant_id, limit=10000, since_date=since_date)
                    stale_candidates = [c for c in stale_candidates]
                    progress_bar = st.progress(0, text="Reclassifying...")
                    for i, contact in enumerate(stale_candidates):
                        orchestrator.classify_and_store(tenant_id, contact["contact_id"], tenant_config=tenant_cfg)
                        progress_bar.progress((i + 1) / max(len(stale_candidates), 1), text=f"{i+1}/{len(stale_candidates)}")
                    st.success(f"Reclassified {len(stale_candidates)} contacts.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Reclassification failed: {e}")

    st.divider()

    # Draft editor
    st.subheader("Draft Editor")

    if draft_config is None:
        if active_config:
            if st.button("Create new draft from active", key="create_draft_btn"):
                save_classifier_draft(
                    tenant_id,
                    active_config["master_prompt"],
                    active_config["stages"],
                    notes="",
                )
                st.rerun()
        else:
            st.info("No active config to draft from. Seed configs first.")
    else:
        st.caption(f"Editing draft v{draft_config.get('version', '?')} — not yet active")

        # Master prompt editor
        MAX_SOFT = 8192
        MAX_HARD = 20 * 1024
        draft_prompt = st.text_area(
            "Master prompt",
            value=draft_config.get("master_prompt", ""),
            height=400,
            key="draft_prompt_area",
        )
        prompt_bytes = len(draft_prompt.encode())
        if prompt_bytes > MAX_HARD:
            st.error(f"Prompt too large ({prompt_bytes} bytes). Hard cap is {MAX_HARD} bytes.")
        elif prompt_bytes > MAX_SOFT:
            st.warning(f"Prompt is large ({prompt_bytes} bytes). Consider trimming below 8 KB.")
        else:
            st.caption(f"{prompt_bytes} bytes")

        # Stage editor
        st.markdown("**Journey stages**")
        stage_df_data = [
            {
                "display_order": s.get("display_order", i),
                "stage_name": s["stage_name"],
                "stage_description": s["stage_description"],
            }
            for i, s in enumerate(draft_config.get("stages", []))
        ]
        edited_stages_df = st.data_editor(
            pd.DataFrame(stage_df_data),
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "stage_name": st.column_config.TextColumn("Stage name", disabled=False),
                "stage_description": st.column_config.TextColumn("Description", width="large"),
                "display_order": st.column_config.NumberColumn("Order", width="small"),
            },
            key="stages_editor",
        )

        # Draft notes
        draft_notes = st.text_input(
            "Notes (optional)", value=draft_config.get("notes") or "", key="draft_notes"
        )

        # Composed prompt preview
        with st.expander("Composed prompt preview"):
            from classifiers.orchestrator import _compose_prompt
            try:
                preview_stages = edited_stages_df.to_dict("records")
                st.code(_compose_prompt(draft_prompt, preview_stages), language=None)
            except Exception as e:
                st.warning(f"Preview error: {e}")

        # Test runner
        st.markdown("**Test classification**")
        test_size = st.radio("Test with", [5, 20], horizontal=True, key="test_size_radio")
        test_result_key = f"test_results_{draft_config['config_id']}"

        if st.button(f"Test with {test_size} contacts", key="test_btn"):
            if prompt_bytes > MAX_HARD:
                st.error("Prompt too large — save a smaller prompt first.")
            else:
                try:
                    from classifiers.factory import get_classifier
                    from classifiers.orchestrator import JourneyClassifier, _compose_prompt

                    provider = get_classifier()
                    orchestrator = JourneyClassifier(classifier=provider)
                    stages_for_test = edited_stages_df.to_dict("records")
                    composed = _compose_prompt(draft_prompt, stages_for_test)

                    from supabase_client import get_supabase_client
                    db = get_supabase_client()
                    sample_resp = (
                        db.schema("silver").table("journey_intent_results")
                        .select("contact_id, journey_stage")
                        .eq("tenant_id", tenant_id)
                        .limit(200)
                        .execute()
                    )
                    sample_pool = sample_resp.data or []
                    if len(sample_pool) >= test_size:
                        import random
                        by_stage: dict = {}
                        for row in sample_pool:
                            by_stage.setdefault(row["journey_stage"], []).append(row["contact_id"])
                        selected = []
                        for stage_contacts in by_stage.values():
                            selected.extend(random.sample(stage_contacts, min(1, len(stage_contacts))))
                        remaining = max(0, test_size - len(selected))
                        if remaining > 0:
                            leftover = [r["contact_id"] for r in sample_pool if r["contact_id"] not in set(selected)]
                            selected += random.sample(leftover, min(remaining, len(leftover)))
                        contact_ids = selected[:test_size]
                    else:
                        contact_ids = [r["contact_id"] for r in sample_pool[:test_size]]

                    results = []
                    prog = st.progress(0, text="Testing...")
                    for i, cid in enumerate(contact_ids):
                        result = orchestrator.classify_contact(
                            tenant_id, cid,
                            tenant_config=(draft_prompt, stages_for_test, draft_config.get("version", 0)),
                            prompt=composed,
                        )
                        stored = next((r["journey_stage"] for r in sample_pool if r["contact_id"] == cid), "—")
                        results.append({
                            "contact_id": cid[:8] + "...",
                            "stored_label": stored,
                            "new_label": result.journey_stage,
                            "confidence": round(result.confidence, 2),
                            "reasoning": (result.raw_response or {}).get("reasoning", ""),
                        })
                        prog.progress((i + 1) / len(contact_ids))

                    st.session_state[test_result_key] = results
                    st.success(f"Tested {len(results)} contacts.")
                except Exception as e:
                    st.error(f"Test failed: {e}")

        if test_result_key in st.session_state:
            st.dataframe(pd.DataFrame(st.session_state[test_result_key]), use_container_width=True, hide_index=True)

        if get_classify_since_date(tenant_id):
            classification_since_date = st.date_input("Classify since", value=get_classify_since_date(tenant_id), format="DD-MM-YYYY")
        else:
            classification_since_date = st.date_input("Classify since", format="DD-MM-YYYY")

        # Action buttons
        st.markdown("---")
        action_cols = st.columns([1, 1, 1, 1])

        with action_cols[0]:
            if st.button("Save draft", type="primary", key="save_draft_btn"):
                if classification_since_date:
                    set_classify_since_date(tenant_id, classification_since_date.isoformat())
                if prompt_bytes > MAX_HARD:
                    st.error("Prompt too large.")
                else:
                    stages_to_save = edited_stages_df.to_dict("records")
                    _, ok = save_classifier_draft(tenant_id, draft_prompt, stages_to_save, draft_notes or None)
                    if ok:
                        st.success("Draft saved.")
                        st.rerun()
                    else:
                        st.error("Save failed.")

        with action_cols[1]:
            activate_enabled = test_result_key in st.session_state
            if st.button("Activate", type="secondary", key="activate_btn", disabled=not activate_enabled):
                stages_to_activate = edited_stages_df.to_dict("records")
                _, save_ok = save_classifier_draft(tenant_id, draft_prompt, stages_to_activate, draft_notes or None)
                if not save_ok:
                    st.error("Could not save draft before activating.")
                    st.stop()
                _, ok = activate_classifier_config(tenant_id, draft_config["config_id"])
                if ok:
                    st.session_state.pop(test_result_key, None)
                    st.success("Config activated.")
                    st.rerun()
                else:
                    st.error("Activation failed.")
            if not activate_enabled:
                st.caption("Run a test first to enable Activate.")

        with action_cols[2]:
            if st.button("Discard draft", key="discard_btn"):
                try:
                    from supabase_client import get_supabase_client
                    db = get_supabase_client()
                    db.table("tenant_classifier_configs").delete().eq("config_id", draft_config["config_id"]).execute()
                    st.session_state.pop(test_result_key, None)
                    st.rerun()
                except Exception as e:
                    st.error(f"Discard failed: {e}")

    st.divider()

    # Version history
    st.subheader("Version history")
    history, _ = get_classifier_version_history(tenant_id, limit=10)
    if history:
        history_df = pd.DataFrame([
            {
                "version": h["version"],
                "active": "Y" if h["is_active"] else "",
                "created": (h.get("created_at") or "")[:10],
                "activated": (h.get("activated_at") or "")[:10],
                "notes": h.get("notes") or "",
            }
            for h in history
        ])
        st.dataframe(history_df, use_container_width=True, hide_index=True)

        restore_version = st.selectbox(
            "Restore version as new draft",
            options=[h["version"] for h in history if not h["is_active"]],
            index=None,
            placeholder="Select version...",
            key="restore_version_select",
        )
        if restore_version and st.button("Restore as draft", key="restore_btn"):
            source = next((h for h in history if h["version"] == restore_version), None)
            if source:
                from supabase_client import get_supabase_client
                db = get_supabase_client()
                s_resp = db.table("tenant_journey_stages").select("*").eq("config_id", source["config_id"]).order("display_order").execute()
                _, ok = save_classifier_draft(tenant_id, source.get("master_prompt", ""), s_resp.data or [], f"Restored from v{restore_version}")
                if ok:
                    st.success(f"v{restore_version} restored as draft.")
                    st.rerun()
    else:
        st.info("No classifier versions yet.")
