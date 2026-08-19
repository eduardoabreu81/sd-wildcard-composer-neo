import launch

packages = {
    "yaml": "pyyaml",
}

if __name__ == "__main__":
    for package_name, package in packages.items():
        try:
            if not launch.is_installed(package_name):
                launch.run_pip(f"install {package}", f"sd-webui-wildcard-composer: {package_name}")
        except Exception as e:
            print(e)
            print(f"Warning: Failed to install {package} for sd-webui-wildcard-composer.")
