import sqlite3
from pathlib import Path

SCHEMA="""
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS evidence(event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,object_id TEXT NOT NULL,event_time TEXT NOT NULL,sha256 TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS segment_revision(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),segment_id TEXT NOT NULL,from_node TEXT NOT NULL,to_node TEXT NOT NULL,version INTEGER NOT NULL,direction TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS closure_notice(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),segment_id TEXT NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL,decision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS map_shape(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),segment_id TEXT NOT NULL,coordinates TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS map_bundle(id INTEGER PRIMARY KEY AUTOINCREMENT,as_of TEXT NOT NULL,manifest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS network_release(as_of TEXT PRIMARY KEY,edges_json TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hazard_case(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),case_id TEXT NOT NULL,segment_id TEXT NOT NULL,severity INTEGER NOT NULL,status TEXT NOT NULL,reporter TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS remediation_order(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),case_id TEXT NOT NULL,worker TEXT NOT NULL,photo_hash TEXT NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS patrol_witness(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),case_id TEXT NOT NULL,reviewer TEXT NOT NULL,photo_hash TEXT NOT NULL,decision TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS shuttle_trip(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),trip_id TEXT NOT NULL,from_node TEXT NOT NULL,to_node TEXT NOT NULL,departs_at TEXT NOT NULL,arrives_at TEXT NOT NULL,seats INTEGER NOT NULL,status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS transfer_demand(event_id TEXT PRIMARY KEY REFERENCES evidence(event_id),demand_id TEXT NOT NULL,from_node TEXT NOT NULL,to_node TEXT NOT NULL,people INTEGER NOT NULL,latest_exit TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seat_reservation(demand_id TEXT NOT NULL,trip_id TEXT NOT NULL,seats INTEGER NOT NULL,decision TEXT NOT NULL,PRIMARY KEY(demand_id,trip_id));
CREATE TABLE IF NOT EXISTS evacuation_plan(demand_id TEXT PRIMARY KEY,covered INTEGER NOT NULL,uncovered INTEGER NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access_receipt(id INTEGER PRIMARY KEY AUTOINCREMENT,demand_id TEXT NOT NULL,as_of TEXT NOT NULL,decision TEXT NOT NULL,reason TEXT NOT NULL,evidence TEXT NOT NULL);
"""

def connect(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path);db.row_factory=sqlite3.Row;db.executescript(SCHEMA);return db

def rows(db,sql,args=()):return [dict(r) for r in db.execute(sql,args).fetchall()]


