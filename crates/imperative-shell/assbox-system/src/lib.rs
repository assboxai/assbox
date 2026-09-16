// SPDX-License-Identifier: GPL-3.0-or-later
#![forbid(unsafe_code)]
//! Linux adapters. No application, boot, storage-selection or reboot policy belongs here.
pub mod commands;
pub mod files;
pub mod probe;

mod mounts;
