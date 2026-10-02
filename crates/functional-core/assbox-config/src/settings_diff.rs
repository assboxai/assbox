// SPDX-License-Identifier: GPL-3.0-or-later
//! Bounded, context-free settings preview. Never print unchanged credentials.
use assbox_domain::{Error, Result};

pub fn render(before: &str, after: &str) -> Result<String> {
    if before.len() > 262_144 || after.len() > 262_144 {
        return Err(Error::new(
            "settings exceed the configure preview size limit",
        ));
    }
    let old: Vec<_> = before.lines().collect();
    let new: Vec<_> = after.lines().collect();
    if old.len() > 1024 || new.len() > 1024 {
        return Err(Error::new(
            "settings exceed the configure preview line limit",
        ));
    }
    let mut common = vec![vec![0usize; new.len() + 1]; old.len() + 1];
    for i in (0..old.len()).rev() {
        for j in (0..new.len()).rev() {
            common[i][j] = if old[i] == new[j] {
                common[i + 1][j + 1] + 1
            } else {
                common[i + 1][j].max(common[i][j + 1])
            };
        }
    }
    let mut output = String::new();
    let (mut i, mut j) = (0, 0);
    while i < old.len() || j < new.len() {
        if i < old.len() && j < new.len() && old[i] == new[j] {
            i += 1;
            j += 1;
        } else if i < old.len() && (j == new.len() || common[i + 1][j] >= common[i][j + 1]) {
            line(&mut output, '-', old[i]);
            i += 1;
        } else {
            line(&mut output, '+', new[j]);
            j += 1;
        }
    }
    if output.is_empty() {
        return Ok("No generated settings changes.\n".into());
    }
    Ok(format!(
        "Settings changes (- current, + requested):\n{output}"
    ))
}

fn line(output: &mut String, prefix: char, text: &str) {
    output.push(prefix);
    let lower = text.to_ascii_lowercase();
    if ["password", "secret", "token", "privatekey", "private-key"]
        .iter()
        .any(|word| lower.contains(word))
    {
        output.push_str(" [sensitive setting redacted]");
    } else {
        for c in text.chars() {
            if c.is_control() {
                output.extend(c.escape_default());
            } else {
                output.push(c);
            }
        }
    }
    output.push('\n');
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preview_shows_ordered_changes_without_unchanged_context() {
        let before = "same\nold policy\npassword = unchanged-hash\nsame\nold worker\n";
        let after = "same\nnew policy\npassword = unchanged-hash\nsame\nnew worker\n";
        assert_eq!(
            render(before, after).unwrap(),
            concat!(
                "Settings changes (- current, + requested):\n",
                "-old policy\n+new policy\n-old worker\n+new worker\n"
            )
        );
        assert_eq!(
            render(before, before).unwrap(),
            "No generated settings changes.\n"
        );
    }

    #[test]
    fn changed_secrets_and_terminal_controls_are_not_printed() {
        let preview = render("password = old-hash\n", "password = new-hash\n\u{1b}[2J\n").unwrap();
        assert!(!preview.contains("hash"));
        assert!(!preview.contains('\u{1b}'));
        assert!(preview.contains("+\\u{1b}[2J"));
    }

    #[test]
    fn oversized_local_settings_fail_before_diff_allocation() {
        assert!(render(&"line\n".repeat(1025), "").is_err());
        assert!(render("", &"x".repeat(262_145)).is_err());
    }
}
