//! Foundation layer for Black Arrow.
//!
//! Black Arrow is a shallow fork of the Codex CLI. Everything that makes it a
//! distinct product at the lowest level lives here: what it is called, where it
//! keeps its state, which upstream defaults it overrides, and how its startup
//! is timed. Upstream crates reach into this crate through small, deliberate
//! call sites, so the fork's divergence stays in one directory that upstream
//! never touches.
//!
//! This crate has no workspace dependencies. It is depended on by the crates
//! that resolve the state directory, so it must stay at the bottom of the graph.

pub mod brand;
pub mod defaults;
pub mod paths;
pub mod startup;
