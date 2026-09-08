#define UNICODE
#define _UNICODE
#include <windows.h>
#include <string>
#include <vector>

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR arguments, int) {
    wchar_t location[32768];
    DWORD length = GetModuleFileNameW(nullptr, location, 32768);
    if (!length || length >= 32768) return 1;
    std::wstring root(location, length);
    root.resize(root.find_last_of(L"\\/"));
    const auto python = root + L"\\.venv\\Scripts\\pythonw.exe";
    const auto entry = root + L"\\tools\\desktop_entry.py";
    for (const auto& path : {python, entry, root + L"\\main.py"}) {
        if (GetFileAttributesW(path.c_str()) == INVALID_FILE_ATTRIBUTES) {
            MessageBoxW(nullptr,
                L"找不到项目文件或 Python 环境。\n请把启动器保留在原项目目录，通过快捷方式启动。",
                L"实时双语字幕", MB_OK | MB_ICONERROR);
            return 1;
        }
    }
    std::wstring command = L"\"" + python + L"\" \"" + entry + L"\" " + arguments;
    std::vector<wchar_t> buffer(command.begin(), command.end());
    buffer.push_back(0);
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(python.c_str(), buffer.data(), nullptr, nullptr, FALSE,
                        CREATE_NO_WINDOW, nullptr, root.c_str(), &startup, &process)) {
        MessageBoxW(nullptr, L"无法启动字幕程序。请检查项目目录和 Python 环境。",
                    L"实时双语字幕", MB_OK | MB_ICONERROR);
        return 1;
    }
    CloseHandle(process.hThread);
    DWORD result = 0;
    if (std::wstring(arguments) == L"--launcher-check") {
        if (WaitForSingleObject(process.hProcess, 30000) == WAIT_OBJECT_0)
            GetExitCodeProcess(process.hProcess, &result);
        else result = 2;
    }
    CloseHandle(process.hProcess);
    return static_cast<int>(result);
}
