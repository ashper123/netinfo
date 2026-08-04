Register-ArgumentCompleter -Native -CommandName netinfo -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)

    $opts = @(
        '--json',
        '--sweep',
        '--vendors',
        '--no-dns',
        '--no-color',
        '--save',
        '--compare',
        '--version',
        '--help'
    )

    $opts | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object {
        [System.Management.Automation.CompletionResult]::new($_, $_, 'ParameterValue', $_)
    }
}
