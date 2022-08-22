import os
import subprocess
from typing import Generator, Optional, Tuple

import click
import gitlab
import yaml


def get_config_file(*, path):
    """
    Parse and return our yaml config file
    """
    with open(path, "r") as stream:
        try:
            return yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            print(exc)
    return None

def clone_gitlab_projects(*, tmp_path: str, user: str, group: Optional[str], project: Optional[str]) -> None:
    """
    Clone gitlab projects for a given user and/or group into a temporary folder
    """
    try:
        gl = gitlab.Gitlab()
        gl_user = gl.users.list(username=user)[0]
        gl_projects = []
        if group:
            gl_group = gl.groups.list(search=group)[0]
            gl_projects = gl_group.projects.list(get_all=True)
        else:
            gl_projects = gl_user.projects.list(get_all=True)
        for gl_project in gl_projects:
            if project and project not in gl_project.name:
                continue
            print(f"Cloning {gl_project.name}...")
            subprocess.run(["git", "clone", gl_project.ssh_url_to_repo, "--recursive", f"{tmp_path}/{gl_project.name}"])
    except Exception as exc:
        print("Error occured while fetching gitlab API")
        print(exc)

def iter_git_repos(*, root: str) -> Generator[Tuple[str, str], None, None]:
    """
    Iterate over folders that are git repositories
    """
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue  # skip files
        git_directory = os.path.join(path, ".git")
        if not os.path.exists(git_directory):
            continue  # skip directories that are not git repos
        yield name, path


def change_old_commit_authors(*, yaml_config, tmp_path: str) -> None:
    """
    Change old commit email to github one
    """

    os.chdir(tmp_path)

    subprocess.run(["git", "config", "user.name", yaml_config["git"]["config"]["name"]])
    subprocess.run(["git", "config", "user.email", yaml_config["git"]["config"]["email"]])

    my_env = os.environ.copy()
    my_env["GIT_SEQUENCE_EDITOR"] = "sed -i -re \'s/^pick /e /\'"
    subprocess.run(["git", "rebase", "-i", "--root"], env=my_env)

    while True:
        author_email = subprocess.run(["git",  "show", "-s", "--format='%ae'"], capture_output=True, text=True).stdout.strip("\n").strip("\'")

        for git_author in yaml_config["git"]["update"]:
            if author_email in git_author["old"]:
                subprocess.run(["git", "commit", "--amend", f'--author="{git_author["new"]["name"]} <{git_author["new"]["email"]}>"', "--no-edit"])
                break

        if subprocess.run(["git", "rebase", "--continue"]).returncode != 0:
            break

def github_fix_commit_dates() -> None:
    """
    Github considers the author date as the main source of truth for the date of commit
    meanwhile Gitlab considers the committer date
    """
    subprocess.run(["git", "filter-branch", "--env-filter", 'export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"'])

@click.command()
@click.option('--config-file', default="config.yaml", show_default=True)
@click.option('--gitlab-user')
@click.option('--gitlab-group')
@click.option('--gitlab-project')
@click.option('--github-user', required=True)
@click.option('--github-repos-path', default="~/", show_default=True)
@click.option('--github-repos-prefix', default="", show_default=True)
def run(config_file: str, gitlab_user: Optional[str], gitlab_group: Optional[str], gitlab_project: Optional[str], github_user: str, github_repos_path: str, github_repos_prefix: str) -> None:
    """
    Import gitlab projects of a group or user to a given github user
    """
    yaml_config = get_config_file(path=config_file)

    if gitlab_user:
        tmp_path_gitlab_projects = "/tmp/gl_projects"
        subprocess.run(["rm", "-Rf", tmp_path_gitlab_projects])
        subprocess.run(["mkdir", "-p", tmp_path_gitlab_projects])
        clone_gitlab_projects(tmp_path=tmp_path_gitlab_projects, user=gitlab_user, group=gitlab_group, project=gitlab_project)
        github_repos_path = tmp_path_gitlab_projects

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

        change_old_commit_authors(yaml_config=yaml_config, tmp_path=tmp_path)

        github_fix_commit_dates()

        if subprocess.run(["gh", "repo", "create", f"{github_user}/{repo_name}", "--public", f"--source={tmp_path}", "--remote=github", "--push"]).returncode != 0:
            if subprocess.run(["git", "remote", "add", "github", f"git@github.com:{github_user}/{repo_name}.git"]).returncode != 0:
                subprocess.run(["git", "remote", "set-url", "github", f"git@github.com:{github_user}/{repo_name}.git"])
            subprocess.run(["git", "push", "github", "--force"])

if __name__ == "__main__":
    run()
