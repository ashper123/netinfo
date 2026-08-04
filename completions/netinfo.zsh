#compdef netinfo

_netinfo() {
    _arguments -s \
        '--json[Output machine-readable JSON]' \
        '--sweep[Perform 64-worker parallel ping sweep]' \
        '--vendors[Lookup MAC OUI vendors online]' \
        '--no-dns[Skip reverse-DNS hostname resolution]' \
        '--no-color[Disable ANSI color output]' \
        '--save[Save report snapshot to JSON file]:file:_files' \
        '--compare[Compare report against a saved snapshot file]:file:_files' \
        '--version[Display version]' \
        '--help[Display help]'
}

_netinfo "$@"
