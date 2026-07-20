on run
	set appPath to (POSIX path of (path to home folder)) & "Applications/Transcriber.app"
	set healthURL to "http://127.0.0.1:7860/"

	try
		do shell script "/bin/test -d " & quoted form of appPath
	on error
		display dialog "Транскрибатор не найден в ~/Applications." & return & "Обратитесь к владельцу сборки." buttons {"OK"} default button "OK" with icon stop
		return
	end try

	if serviceIsReady(healthURL) then
		do shell script "/usr/bin/open " & quoted form of healthURL
		return
	end if

	set executablePath to appPath & "/Contents/MacOS/Transcriber"
	do shell script quoted form of executablePath & " >/dev/null 2>&1 &"

	repeat with attempt from 1 to 60
		delay 1
		if serviceIsReady(healthURL) then
			do shell script "/usr/bin/open " & quoted form of healthURL
			return
		end if
	end repeat

	display dialog "Транскрибатор не запустился за 60 секунд." & return & "Закройте его через значок в строке меню и попробуйте ещё раз." buttons {"OK"} default button "OK" with icon caution
end run

on serviceIsReady(healthURL)
	try
		do shell script "/usr/bin/curl --fail --silent --max-time 1 " & quoted form of healthURL & " >/dev/null"
		return true
	on error
		return false
	end try
end serviceIsReady
