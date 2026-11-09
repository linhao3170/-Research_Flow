# Stage 7: read-only Word page map for the authoritative DOCX.
# Opens the document read-only, never saves, and records heading page numbers.
$ErrorActionPreference = 'Stop'
$src = 'D:\ResearchFlow-project\ResearchFlow_3.1_项目策划书_v4.3.1_完整开发版.docx'
$out = 'D:\ResearchFlow-project\docs\verification\stage7\06_docx_page_map.txt'

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $word.AutomationSecurity = 3  # msoAutomationSecurityForceDisable
    # Open(FileName, ConfirmConversions, ReadOnly, AddToRecentFiles, PasswordDocument, ...)
    $doc = $word.Documents.Open($src, $false, $true, $false, '', '', $false, '', '', 0, 65001, $false, $true, 0, $true)

    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('STAGE7 WORD PAGE MAP (read-only)')
    $lines.Add('PATH=' + $src)
    $statPages = $doc.ComputeStatistics(2)   # wdStatisticPages
    $statWords = $doc.ComputeStatistics(0)   # wdStatisticWords
    $statChars = $doc.ComputeStatistics(3)   # wdStatisticCharacters
    $lines.Add('WORD_PAGES=' + $statPages)
    $lines.Add('WORD_WORDS=' + $statWords)
    $lines.Add('WORD_CHARACTERS=' + $statChars)
    $lines.Add('')
    $lines.Add('FORMAT: page | outlineLevel | style | text')

    $i = 0
    foreach ($p in $doc.Paragraphs) {
        $i++
        $styleName = ''
        try { $styleName = [string]$p.Style.NameLocal } catch { $styleName = '(unknown)' }
        $outline = 10
        try { $outline = [int]$p.OutlineLevel } catch { $outline = 10 }
        $text = [string]$p.Range.Text
        $text = $text -replace "[\r\n\a]", ' '
        $text = $text.Trim()
        if ($outline -lt 10 -or $styleName -match 'Heading|标题|TOC') {
            $page = [int]$p.Range.Information(3)  # wdActiveEndPageNumber
            $lines.Add(('{0} | {1} | {2} | {3}' -f $page, $outline, $styleName, $text))
        }
    }
    $lines.Add('')
    $lines.Add('PARAGRAPH_ENUMERATED=' + $i)
    [System.IO.File]::WriteAllLines($out, $lines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Output ('PAGE_MAP=OK PAGES=' + $statPages + ' HEADING_LINES=' + ($lines.Count - 6))
}
finally {
    if ($doc -ne $null) {
        try { $doc.Close($false) } catch { }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($doc) | Out-Null
    }
    if ($word -ne $null) {
        try { $word.Quit($false) } catch { }
        [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
