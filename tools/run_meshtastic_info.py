from main import run_cli_command

if __name__ == '__main__':
    print('Calling run_cli_command(["--info"])')
    out = run_cli_command(['--info'])
    print('Output:\n', out)
