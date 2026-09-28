/* PraatAiProjectDirectory.h
 *
 * Locate the repository's AI support directory without mistaking stale
 * runtime files for an installed project.
 */

#ifndef _PraatAiProjectDirectory_h_
#define _PraatAiProjectDirectory_h_

#include <algorithm>
#include <filesystem>
#include <optional>
#include <system_error>
#include <vector>

namespace PraatAiProjectDirectory {
	inline bool isProjectDirectory (const std::filesystem::path &directory) {
		const auto isRegularFile = [] (const std::filesystem::path &path) {
			std::error_code error;
			return std::filesystem::is_regular_file (path, error) && ! error;
		};
		return isRegularFile (directory / "run_ai_control.py") &&
			isRegularFile (directory / "praat_ai" / "launch_vot_worker.py");
	}

	inline std::optional <std::filesystem::path> resolve (
		const std::filesystem::path &configuredDirectory,
		const std::filesystem::path &currentDirectory,
		const std::filesystem::path &executableDirectory
	) {
		std::vector <std::filesystem::path> directCandidates;
		if (configuredDirectory.is_absolute()) {
			directCandidates.push_back (configuredDirectory);
		} else {
			directCandidates.push_back (currentDirectory / configuredDirectory);
			if (executableDirectory != currentDirectory)
				directCandidates.push_back (executableDirectory / configuredDirectory);
		}
		for (const auto &candidate : directCandidates)
			if (isProjectDirectory (candidate))
				return candidate.lexically_normal ();

		/*
			A development build can live next to the checkout while its default
			"ai" directory is a child of that checkout. Search one directory level
			for a unique, complete project; never infer it from runtime/status.json.
		*/
		const std::filesystem::path projectName = configuredDirectory.filename ();
		if (projectName.empty () || projectName == "." || projectName == ".." ||
			projectName.has_parent_path ())
			return {};

		std::vector <std::filesystem::path> discovered;
		for (const auto &base : { currentDirectory, executableDirectory }) {
			std::error_code iteratorError;
			std::filesystem::directory_iterator iterator (base, iteratorError), end;
			while (! iteratorError && iterator != end) {
				std::error_code directoryError;
				if (std::filesystem::is_directory (iterator -> path (), directoryError) && ! directoryError) {
					const std::filesystem::path candidate = iterator -> path () / projectName;
					if (isProjectDirectory (candidate))
						discovered.push_back (candidate.lexically_normal ());
				}
				iterator.increment (iteratorError);
			}
		}
		std::sort (discovered.begin (), discovered.end ());
		discovered.erase (std::unique (discovered.begin (), discovered.end ()), discovered.end ());
		if (discovered.size () == 1)
			return discovered.front ();
		return {};
	}
}

#endif
