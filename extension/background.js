// 툴바 아이콘을 누르면 설정 화면(도우미 서버 주소 등록)을 연다.
chrome.action.onClicked.addListener(() => chrome.runtime.openOptionsPage());
