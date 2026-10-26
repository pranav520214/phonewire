package com.phonemic.app.data

data class HistoryItem(
    val id: String,
    val text: String,
    val timestamp: Long,
    val inserted: Boolean,
    val status: String
)
