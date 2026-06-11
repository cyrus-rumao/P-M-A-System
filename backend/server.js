require('dotenv').config()

const express = require('express')
const connectDB = require('./Config/db')

const app = express()

app.use(express.json())

app.get('/', (_req, res) => {
  res.status(200).json({ message: 'API is running' })
})

const PORT = process.env.PORT || 5000

connectDB().then(() => {
  app.listen(PORT, () => {
    console.log(`Server running on port ${PORT}`)
  })
})
