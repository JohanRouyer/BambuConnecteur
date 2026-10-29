"""État de l'imprimante en réseau local (MQTT, lecture seule)."""
import json
import os
import ssl
import threading

import paho.mqtt.client as mqtt

from . import config

GCODE_STATES = {"IDLE": "au repos", "PREPARE": "préparation", "RUNNING": "impression en cours",
                "PAUSE": "en pause", "FINISH": "terminée", "FAILED": "échouée", "SLICING": "slicing"}


def _ams_trays(ams: dict) -> list[dict]:
    trays = []
    for unit in (ams or {}).get("ams", []) or []:
        for tray in unit.get("tray", []) or []:
            if not tray.get("tray_type"):
                continue
            trays.append({"ams": unit.get("id"), "slot": tray.get("id"), "type": tray.get("tray_type"),
                          "name": tray.get("tray_sub_brands"), "color": tray.get("tray_color"),
                          "remaining_pct": tray.get("remain"), "nozzle_temp_range":
                          [tray.get("nozzle_temp_min"), tray.get("nozzle_temp_max")],
                          "k": tray.get("k")})
    return trays


def status(timeout_s: float = 10, include_raw: bool = False) -> dict:
    cfg = config.printer()
    host, serial, code = cfg.get("host"), cfg.get("serial"), cfg.get("access_code")
    missing = [k for k, v in {"host": host, "serial": serial, "access_code": code}.items() if not v]
    if missing:
        raise ValueError(f"Compléter la section \"printer\" de {config.CONFIG_FILE} : {missing}")

    report: dict = {}
    error: dict = {}
    done = threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"claude-bambu-{os.getpid()}")
    client.username_pw_set("bblp", code)
    # L'imprimante utilise un certificat auto-signé.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    client.tls_set_context(ctx)

    def on_connect(cl, userdata, flags, reason, props):
        if reason.is_failure:
            error["message"] = f"Connexion refusée ({reason}) : vérifier le code d'accès et le mode LAN."
            done.set()
            return
        cl.subscribe(f"device/{serial}/report")
        cl.publish(f"device/{serial}/request",
                   json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))

    def on_message(cl, userdata, msg):
        try:
            data = json.loads(msg.payload)
        except ValueError:
            return
        if "gcode_state" in data.get("print", {}):
            report.update(data["print"])
            done.set()

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(host, 8883, keepalive=30)
    except OSError as exc:
        raise ConnectionError(f"Imprimante injoignable sur {host}:8883 ({exc}).") from exc
    client.loop_start()
    done.wait(timeout_s)
    client.loop_stop()
    client.disconnect()
    if error:
        raise ConnectionError(error["message"])
    if not report:
        raise TimeoutError("Aucun état reçu. L'imprimante est-elle allumée et sur le même réseau ?")

    p = report
    state = p.get("gcode_state")
    result = {
        "state": state, "state_fr": GCODE_STATES.get(state, state),
        "job": p.get("subtask_name") or None, "progress_pct": p.get("mc_percent"),
        "remaining_min": p.get("mc_remaining_time"),
        "layer": f"{p.get('layer_num')}/{p.get('total_layer_num')}" if p.get("total_layer_num") else None,
        "nozzle_c": {"current": p.get("nozzle_temper"), "target": p.get("nozzle_target_temper")},
        "bed_c": {"current": p.get("bed_temper"), "target": p.get("bed_target_temper")},
        "chamber_c": p.get("chamber_temper"),
        "fans": {"part": p.get("cooling_fan_speed"), "aux": p.get("big_fan1_speed"),
                 "chamber": p.get("big_fan2_speed")},
        "speed_level": p.get("spd_lvl"), "nozzle_diameter": p.get("nozzle_diameter"),
        "nozzle_type": p.get("nozzle_type"), "print_error": p.get("print_error") or None,
        "hms_errors": p.get("hms") or [], "ams": _ams_trays(p.get("ams")),
        "external_spool": {k: (p.get("vt_tray") or {}).get(k) for k in ("tray_type", "tray_color", "k")},
        "wifi_signal": p.get("wifi_signal"),
    }
    if include_raw:
        result["raw"] = report
    return result
