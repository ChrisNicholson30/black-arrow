//! The items Black Arrow adds to the default status line.
//!
//! The list itself is policy and lives in `blackarrow_base::defaults`, which
//! cannot see the TUI's item type. These tests are what tie the two together:
//! an id that upstream renames, or one upstream starts showing by default
//! itself, fails here instead of quietly vanishing from the screen.

use super::super::DEFAULT_STATUS_LINE_ITEMS;
use crate::bottom_pane::StatusLineItem;
use blackarrow_base::defaults::Defaults;
use pretty_assertions::assert_eq;

#[test]
fn the_added_items_are_real_status_line_items() {
    let added: Vec<StatusLineItem> = Defaults::BLACK_ARROW
        .extra_status_line_items
        .iter()
        .map(|id| {
            id.parse()
                .unwrap_or_else(|_| panic!("{id:?} is not a status line item"))
        })
        .collect();

    assert_eq!(added, vec![StatusLineItem::WeeklyLimit]);
}

#[test]
fn the_added_items_are_not_already_in_upstreams_default() {
    for id in Defaults::BLACK_ARROW.extra_status_line_items {
        assert!(
            !DEFAULT_STATUS_LINE_ITEMS.contains(id),
            "{id:?} would be shown twice"
        );
    }
}

/// Upstream's tests assert upstream's status line, so its defaults add nothing.
#[test]
fn upstreams_defaults_add_nothing() {
    assert_eq!(Defaults::UPSTREAM.extra_status_line_items, [] as [&str; 0]);
}
