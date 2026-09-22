"""Tutorial markdown documents exposed to the local Web UI."""

from backend.service.tutorial import TutorialDocument, TutorialService, TutorialSummary


class TutorialRouter:
    """Read local tutorial markdown files for the help menu."""

    def list_tutorials(self) -> list[TutorialSummary]:
        """Return tutorial entries for the title-bar help menu."""
        return TutorialService.list_tutorials()

    def get_tutorial(self, tutorial_id: str) -> TutorialDocument:
        """Return one tutorial's markdown content, looked up by file name."""
        return TutorialService.get_tutorial(tutorial_id)
