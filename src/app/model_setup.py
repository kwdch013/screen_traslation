from __future__ import annotations

from collections.abc import Sequence
from typing import cast, Protocol

from .errors import DependencyUnavailableError


class ArgosPackageMetadata(Protocol):
    from_code: str
    to_code: str


class ArgosPackage(ArgosPackageMetadata, Protocol):
    def download(self) -> str: ...


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
    package_path = cast(ArgosPackage, selected_package).download()
    package.install_from_path(package_path)
    return str(package_path)


def find_argos_package(
    packages: Sequence[ArgosPackageMetadata],
    source_language: str,
    target_language: str,
) -> ArgosPackageMetadata | None:
    for candidate in packages:
        if (
            getattr(candidate, "from_code", None) == source_language
            and getattr(candidate, "to_code", None) == target_language
        ):
            return candidate
    return None
