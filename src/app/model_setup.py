from __future__ import annotations

from .errors import DependencyUnavailableError


def install_argos_package(source_language: str = "en", target_language: str = "ja") -> str:
    try:
        from argostranslate import package
    except ImportError as error:
        raise DependencyUnavailableError(
            "Argos Translateモデルの導入には argostranslate が必要です。"
        ) from error

    package.update_package_index()
    selected_package = find_argos_package(
        package.get_available_packages(),
        source_language,
        target_language,
    )
    if selected_package is None:
        raise DependencyUnavailableError(f"{source_language}->{target_language} のArgosパッケージが見つかりません。")
    package_path = selected_package.download()
    package.install_from_path(package_path)
    return str(package_path)


def find_argos_package(packages: list[object], source_language: str, target_language: str) -> object | None:
    for candidate in packages:
        if (
            getattr(candidate, "from_code", None) == source_language
            and getattr(candidate, "to_code", None) == target_language
        ):
            return candidate
    return None
