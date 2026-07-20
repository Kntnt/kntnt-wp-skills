# help

## NAME

`help` — show the plugin overview or a skill's manual page

## SYNOPSIS

```
/kntnt-wp-skills:help [skill]
/kntnt-wp-skills:help help
```

## DESCRIPTION

`help` is the plugin's manual reader. With no argument it prints the overview — the plugin's name, version, and blurb, then one line per skill. Given a skill name it echoes that skill's full manual page (`NAME`, `SYNOPSIS`, `DESCRIPTION`, `OPTIONS`, `EXAMPLES`, `FILES`) verbatim. Given anything it does not recognise it prints a one-line error naming the known skills.

The manual pages under `docs/man/` are the single source of truth: `help` reads them and the plugin manifest and echoes the result as GitHub-flavoured Markdown, which the terminal renders. The same pages back the per-skill help gate, so `/kntnt-wp-skills:clone --help` and `/kntnt-wp-skills:help clone` reach the same text.

`help` is itself a command rather than a skill, so it is not listed under *Skills* in the overview — but it is self-documenting: `/kntnt-wp-skills:help help` shows this page. It is user-invoked only and changes nothing; it reads the plugin's own files and prints.

## OPTIONS

| Option | Description |
|---|---|
| `skill` | Name of a skill (`clone`, `pull`, `mkwp`, `build-ollie-site`) whose full manual page to echo. Omit it for the overview. |
| `help` | Show this manual page (the reader documenting itself). |

## EXAMPLES

Print the overview — the blurb and every skill's summary line:

```
/kntnt-wp-skills:help
```

Show the `clone` skill's full manual page:

```
/kntnt-wp-skills:help clone
```

Show this page:

```
/kntnt-wp-skills:help help
```
