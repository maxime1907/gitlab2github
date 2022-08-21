import click
import os
import subprocess
import yaml

from typing import Generator, Tuple

def parse_config_file(*, path) -> None:
    with open(path, "r") as stream:
        try:
            yaml_config = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)

def iter_git_repos(*, root: str) -> Generator[Tuple[str, str], None, None]:
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue  # skip files
        git_directory = os.path.join(path, ".git")
        if not os.path.exists(git_directory):
            continue  # skip directories that are not git repos
        yield name, path


def change_old_commit_authors(*, tmp_path: str) -> None:
    # Change old commit email to github one
    os.chdir(tmp_path)

    subprocess.run(["git", "config", "user.name", yaml_config["config"]["name"]])
    subprocess.run(["git", "config", "user.email", yaml_config["config"]["email"]])

    my_env = os.environ.copy()
    my_env["GIT_SEQUENCE_EDITOR"] = "sed -i -re \'s/^pick /e /\'"
    subprocess.run(["git", "rebase", "-i", "--root"], env=my_env)

    while True:
        author_email = subprocess.run(["git",  "show", "-s", "--format='%ae'"], capture_output=True, text=True).stdout.strip("\n").strip("\'")
        # commit_date = subprocess.run(["git", "log", "-n", "1", "--format=%aD"], capture_output=True, text=True).stdout.strip("\n").strip("\'")

        for git_author in yaml_config["update"]:
            if author_email in git_author["old"]:
                subprocess.run(["git", "commit", "--amend", f'--author="{git_author["new"]["name"]} <{git_author["new"]["email"]}>"', "--no-edit"])
                break

        if subprocess.run(["git", "rebase", "--continue"]).returncode != 0:
            break

def github_fix_commit_dates() -> None:
    subprocess.run(["git", "filter-branch", "--env-filter", 'export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"'])

@click.command()
@click.option('--config-file', default="config.yaml", show_default=True)
@click.option('--github-user')
@click.option('--github-repos-path', default="~/", show_default=True)
@click.option('--github-repos-prefix', default="", show_default=True)
def run(config_file: str, github_user: str, github_repos_path: str, github_repos_prefix: str) -> None:
    parse_config_file(path=config_file)

    process = subprocess.run(["gh", "status"])
    if process.returncode != 0:
        process = subprocess.run(["gh", "auth", "login"], check=True)

    for repo_name, path in iter_git_repos(root=github_repos_path):
        os.chdir(path)

        repo_name = f"{github_repos_prefix}{repo_name}"

        tmp_path = f"/tmp/{repo_name}"

        remote_url = subprocess.run(["git", "config", "--get", "remote.origin.url"], capture_output=True, text=True).stdout.strip("\n")

        subprocess.run(["rm", "-Rf", tmp_path])

        subprocess.run(["git", "clone", remote_url, tmp_path])

        change_old_commit_authors(tmp_path=tmp_path)

        github_fix_commit_dates()

        if subprocess.run(["gh", "repo", "create", f"{github_user}/{repo_name}", "--public", f"--source={tmp_path}", "--remote=github", "--push"]).returncode != 0:
            if subprocess.run(["git", "remote", "add", "github", f"git@github.com:{github_user}/{repo_name}.git"]).returncode != 0:
                subprocess.run(["git", "remote", "set-url", "github", f"git@github.com:{github_user}/{repo_name}.git"])
            subprocess.run(["git", "push", "github", "--force"])

if __name__ == "__main__":
    run()
